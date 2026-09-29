"""O que a maquina pede, e o que volta — como valor, nunca como chamada.

A maquina e pura: cada interacao com o hypervisor ou com o destino e algo que ela
**pede**, nao algo que ela faz. Entre pedir e fazer existem uma fila duravel e uma
rede, entao o efeito nao e uma chamada de funcao adiada: e um registro que viaja.

Ver docs/adr/0015-efeito-como-valor.md. As quatro propriedades, em codigo:

1. efeito serializavel;
2. resultado serializavel e tolerante a repeticao;
3. `ciclo_id` em todo efeito, para descartar resultado atrasado;
4. chave de exclusao em todo efeito que toca disco, com preempcao como unica
   categoria que toma chave ja tomada.

O ENVELOPE e fechado. A varredura em specs/dr-001-dominio-ciclo/plan.md enumerou o
que fila, despachante e reconciliacao precisam ler sem abrir o que o efeito
significa, e decidiu onze itens: quatro viraram campo, sete viraram decisao
registrada de que NAO sao campo. Campo novo aqui exige dizer por que nao estava na
tabela.

Este modulo roda no hypervisor (fecho de 3.9, ADR-0007): sem sintaxe 3.10+.
"""

import enum
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Optional, TypeVar
from uuid import UUID

__all__ = [
    "PREEMPCAO_DESPEJA_DETENTOR",
    "Alvo",
    "CercarDestino",
    "ChaveDeExclusao",
    "ConfirmarNoDestino",
    "ConsultarNoDaVm",
    "CriarCheckpoint",
    "DescartarBitmap",
    "Efeito",
    "EfeitoDeDisco",
    "EfeitoDePreempcao",
    "IniciarCopia",
    "InventariarHypervisor",
    "PublicarExport",
    "Resultado",
    "ResultadoDeCopia",
    "ResultadoDeInventario",
    "ResultadoDeLocalizacao",
    "ResultadoSimples",
    "ValorDesconhecidoError",
    "efeito_de_json",
    "pode_tomar_chave_tomada",
    "resultado_de_json",
]


class ValorDesconhecidoError(ValueError):
    """Valor que esta versao nao interpreta, num campo que carrega regra.

    Campo desconhecido se **ignora** — e o que "evolucao aditiva" significa, e e o
    que permite a versao do contrato nao ser campo. Valor desconhecido de campo
    que decide para onde o efeito vai, com quem ele conflita ou o que ele pode
    atropelar e outra coisa: e recusa.

    Um agente antigo que receba um `alvo` que nao conhece e caia num padrao
    roteia errado, que e o defeito que o proprio `Alvo` existe para impedir. Ele
    devolve o efeito a fila com "contrato mais novo que eu", e alguem ve.

    Mesma regra do `ler_nome` em identidade.py, outro modulo: la a especie
    desconhecida vira um terceiro estado em vez de virar "nao e nosso".
    """


class Alvo(enum.Enum):
    """Por onde se alcanca quem executa o efeito.

    O criterio de nomeacao e **modo de falha, nao geografia**: dois efeitos tem o
    mesmo alvo se, quando um e inentregavel, o outro tambem e.

    Por esse criterio, o agente de um hypervisor e o Nova da nuvem daquele mesmo
    hypervisor sao alvos DIFERENTES. Eles falham separado, e a segunda forma de
    evidencia — "a VM nao esta mais no no gravado" — existe justamente para o caso
    em que o agente nao responde. Com uma enumeracao de dois valores, "origem" e
    "destino", essa consulta seria entregue ao agente, e a evidencia morreria no
    unico cenario em que serve.
    """

    AGENTE_DE_ORIGEM = "agente_de_origem"
    RECEPTORA = "receptora"
    API_DA_NUVEM_DE_ORIGEM = "api_da_nuvem_de_origem"


#: A preempcao COEXISTE com a chave: quem a tinha **mantem** o lease.
#:
#: Nao e campo, e regra — a varredura do envelope decidiu assim, e este e o lugar
#: onde a regra mora para quem a implementa.
#:
#: Preempcao nao precisa de exclusividade; precisa de permissao para agir apesar
#: da chave. Exclusividade existe para impedir dois escritores, e preempcao nao e
#: escritor: ela retira a capacidade de escrever.
#:
#: Despejar abriria caminho ruim alcancavel com o que ja esta decidido: um
#: `CercarDestino` reentregue por retry depois de o ciclo N ter fechado chega
#: idempotente, acha o export ja derrubado, reporta sucesso — e no caminho
#: despeja o lease do N+1, que esta copiando.
PREEMPCAO_DESPEJA_DETENTOR = False


@dataclass(frozen=True)
class ChaveDeExclusao:
    """Dois efeitos com a mesma chave nunca tem lease ao mesmo tempo.

    O `ciclo_id` nao cobre isto, e e facil achar que cobre: os dois efeitos em
    conflito sao do **mesmo** ciclo — o original, que ninguem cancelou, e o
    reemitido depois que o lease caiu. Dois `blockdev-backup` escrevendo o mesmo
    espelho dao resultado indefinido em cima do dado que o cliente vai usar no
    failover. E P1 e P2, nao desenho de protocolo.
    """

    vm_id: UUID
    disco: str

    def para_json(self) -> dict[str, Any]:
        return {"vm_id": str(self.vm_id), "disco": self.disco}

    @classmethod
    def de_json(cls, dados: Mapping[str, Any]) -> "ChaveDeExclusao":
        """Exige, nao coage — e aqui mais que em qualquer outro lugar.

        Este e o campo que guarda P1 e P2. Com `str(dados["disco"])`, um `42`
        virava `"42"`, e a chave reconstruida deixava de ser a chave que a
        maquina criou: dois efeitos que deveriam colidir passavam a nao colidir,
        e a exclusao deixava de excluir — sem erro, com a forma toda certa. Dois
        `blockdev-backup` sobre o mesmo espelho, pela mesma porta do `"false"`.
        """
        return cls(vm_id=_exigir_uuid(dados, "vm_id"), disco=_exigir_texto(dados, "disco"))


@dataclass(frozen=True)
class Efeito:
    """O envelope. Quem despacha le so isto; o resto e conteudo.

    `alvo` e constante da classe e nao campo de instancia, e isso e deliberado: o
    alvo e propriedade da ESPECIE de efeito, nao da ocorrencia. Como campo,
    `CercarDestino(alvo=AGENTE_DE_ORIGEM)` seria construtivel — um bug que o tipo
    pode simplesmente nao permitir. Ele continua viajando no JSON, porque a fila
    so le o que o valor carrega.
    """

    ALVO: ClassVar[Alvo]
    TIPO: ClassVar[str]

    #: P9. A fila isola sem abrir o efeito, e derivar de `vm_id` exigiria consulta
    #: no caminho de despacho. E o **unico** lugar onde tenant e dito: nenhum
    #: corpo repete tenant nem referencia de onde deriva-lo, porque duas
    #: expressoes podem discordar e, com RLS, a segunda vira oraculo de
    #: existencia.
    tenant_id: UUID
    ciclo_id: UUID

    @property
    def alvo(self) -> Alvo:
        return self.ALVO

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "tipo": self.TIPO,
            "tenant_id": str(self.tenant_id),
            "ciclo_id": str(self.ciclo_id),
            "alvo": self.ALVO.value,
        }
        dados.update(self._corpo_json())
        return dados

    def _corpo_json(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class EfeitoDeDisco(Efeito):
    """Efeito que toca disco, e por isso carrega chave de exclusao."""

    vm_id: UUID
    disco: str

    def chave_de_exclusao(self) -> ChaveDeExclusao:
        """Deterministica: mesmo disco, mesma chave, em qualquer ciclo.

        Nao entra o `ciclo_id` de proposito. Se entrasse, dois ciclos sobre o
        mesmo disco teriam chaves diferentes e poderiam escrever juntos — que e
        exatamente o que a chave existe para impedir.
        """
        return ChaveDeExclusao(vm_id=self.vm_id, disco=self.disco)

    def _corpo_json(self) -> dict[str, Any]:
        return {"chave_de_exclusao": self.chave_de_exclusao().para_json()}


@dataclass(frozen=True)
class EfeitoDePreempcao(EfeitoDeDisco):
    """A unica categoria que toma chave ja tomada.

    Sem ela a propriedade 4 torna o cercamento impossivel: `CercarDestino` toca
    disco, logo carrega a chave `(vm, disco)` — que esta presa pela copia zumbi,
    que e a razao de ele existir. O efeito que destrava nao conseguiria lease.

    Categoria, e nao excecao a regra: excecao abre buraco que cresce sozinho,
    porque o proximo efeito parecido vira segunda excecao por analogia. Categoria
    carrega obrigacoes, e sao quatro:

    - toma chave ja tomada — e a definicao;
    - **nunca escreve dado de cliente**, porque preempcao retira capacidade de
      escrever; se escrevesse, seria mais um escritor concorrente;
    - e idempotente por construcao: a segunda tentativa encontra o export ja
      derrubado, e isso e sucesso;
    - **o sucesso dela e evidencia** — derrubado o export, o escritor perdeu o
      alvo. Sem isso cercariamos e continuariamos esperando a chave liberar.

    E coexiste: ver PREEMPCAO_DESPEJA_DETENTOR.
    """


def pode_tomar_chave_tomada(efeito: Efeito) -> bool:
    """So preempcao pode. E por tipo, nao por sinalizador.

    Sinalizador e ativavel por quem nao leu as obrigacoes; tipo obriga a
    herda-las.
    """
    return isinstance(efeito, EfeitoDePreempcao)


# ── Os efeitos ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CriarCheckpoint(EfeitoDeDisco):
    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "criar_checkpoint"


@dataclass(frozen=True)
class IniciarCopia(EfeitoDeDisco):
    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "iniciar_copia"


@dataclass(frozen=True)
class DescartarBitmap(EfeitoDeDisco):
    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "descartar_bitmap"


@dataclass(frozen=True)
class InventariarHypervisor(Efeito):
    """A fotografia do hypervisor, que alimenta a reconciliacao.

    Roteavel por **qualquer** agente com acesso aquele hypervisor, e nunca pedida
    ao detentor do lease: ele e justamente quem nao responde no cenario que a
    reconciliacao existe para cobrir.
    """

    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "inventariar_hypervisor"


@dataclass(frozen=True)
class ConsultarNoDaVm(Efeito):
    """Em que no a VM esta agora — pelo Nova, nao pelo agente.

    E a segunda forma de evidencia: se a VM nao esta mais no no gravado, o
    escritor era o processo QEMU do no antigo e nao existe mais. Sem ela, um no
    morto bloqueia aquele disco para sempre, porque nao ha quem responda o
    inventario.

    Por isso o alvo e a API da nuvem, e nao o agente: sao modos de falha
    diferentes, e este efeito existe para o caso em que o outro nao chega.
    """

    ALVO = Alvo.API_DA_NUVEM_DE_ORIGEM
    TIPO = "consultar_no_da_vm"


@dataclass(frozen=True)
class PublicarExport(EfeitoDeDisco):
    """Publica o export do ciclo na receptora.

    Passo do ciclo, e nao do provisionamento, porque o export e por ciclo.
    Escondido dentro do `IniciarCopia`, a maquina nao conheceria o nome do export
    que criou — e sem esse nome nao ha reconciliacao de orfao nem cercamento por
    instancia.
    """

    ALVO = Alvo.RECEPTORA
    TIPO = "publicar_export"


@dataclass(frozen=True)
class ConfirmarNoDestino(EfeitoDeDisco):
    """P2: a janela so e liberada depois disto."""

    ALVO = Alvo.RECEPTORA
    TIPO = "confirmar_no_destino"


@dataclass(frozen=True)
class CercarDestino(EfeitoDePreempcao):
    """Derruba o export, tirando do zumbi a possibilidade de continuar.

    Nao prova que ele parou: remove o alvo dele. A mecanica QMP e da `dr-006`,
    dona do ciclo de vida do export.
    """

    ALVO = Alvo.RECEPTORA
    TIPO = "cercar_destino"


# ── Os resultados ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Resultado:
    """O que volta.

    Carrega a MESMA tripla que correlaciona: `ciclo_id`, `tipo` do efeito e, nos
    de disco, a chave. Nao existe id de efeito, e isso e decisao e nao esquecimento
    — a correlacao e derivavel do que ja viaja, e id novo seria segunda forma de
    dizer a mesma coisa.

    A correlacao e segura nas tres classes de efeito, e por razoes DIFERENTES.
    Registrar so a primeira seria afirmar uma garantia que duas delas nao tem:

    - **disco, sem preempcao** — a chave de exclusao garante que dois do mesmo
      tipo, ciclo e disco nao ficam pendentes juntos. Aqui a chave e mesmo o
      mecanismo;
    - **preempcao** — a chave NAO garante nada, por definicao: preempcao toma
      chave ja tomada e coexiste com quem a tinha. Dois `CercarDestino` do mesmo
      ciclo e disco podem ficar pendentes juntos, e o caminho esta descrito em
      PREEMPCAO_DESPEJA_DETENTOR: reentrega por retry;
    - **sem chave** — `InventariarHypervisor` e `ConsultarNoDaVm` nao tem chave
      nenhuma, e nada impede dois pendentes.

    Nos dois ultimos casos a correlacao e inofensiva **porque a absorcao e
    idempotente**, e isso e obrigacao e nao coincidencia: preempcao e idempotente
    por construcao, e leitura repetida devolve o mesmo valor. No dia em que
    existir uma preempcao que nao seja idempotente, esta e a linha que reprova a
    ideia — e nao um docstring dizendo que a chave garante o que ela nunca
    garantiu.

    `tenant_id` esta aqui pelo mesmo motivo que esta no efeito: o resultado
    atravessa a mesma fila e a mesma tabela sob RLS, e quem isola nao deveria
    precisar abri-lo. A varredura falava de efeito; a primeira linha dela vale
    para os dois, e esta escrito em vez de deduzido.
    """

    TIPO: ClassVar[str]

    tenant_id: UUID
    ciclo_id: UUID
    tipo_do_efeito: str
    #: Sem padrao: quem nao tem chave passa `None` explicitamente. Com padrao
    #: aqui, toda subclasse seria obrigada a ter padrao tambem — e ai `sucesso`
    #: e `concluido` ganhariam um, o que faria silencio significar sucesso.
    chave: Optional[ChaveDeExclusao]

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "tipo": self.TIPO,
            "tenant_id": str(self.tenant_id),
            "ciclo_id": str(self.ciclo_id),
            "tipo_do_efeito": self.tipo_do_efeito,
        }
        if self.chave is not None:
            dados["chave"] = self.chave.para_json()
        dados.update(self._corpo_json())
        return dados

    def _corpo_json(self) -> dict[str, Any]:
        return {}

    @classmethod
    def _corpo_de_json(cls, dados: Mapping[str, Any]) -> dict[str, Any]:  # noqa: ARG003
        # Resultado sem corpo proprio. O parametro existe porque a assinatura e
        # o contrato que as subclasses cumprem.
        return {}


@dataclass(frozen=True)
class ResultadoSimples(Resultado):
    """Deu certo, ou nao deu.

    `sucesso` nao tem padrao, e isso e deliberado: para um tipo cujo trabalho e
    relatar desfecho, silencio nao pode significar sucesso.
    """

    TIPO = "simples"

    sucesso: bool
    motivo: Optional[str] = None

    def _corpo_json(self) -> dict[str, Any]:
        return {"sucesso": self.sucesso, "motivo": self.motivo}

    @classmethod
    def _corpo_de_json(cls, dados: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "sucesso": _exigir_bool(dados, "sucesso"),
            "motivo": _texto_ou_nada(dados, "motivo"),
        }


@dataclass(frozen=True)
class ResultadoDeCopia(Resultado):
    TIPO = "copia"

    bytes_transferidos: int
    concluido: bool

    def _corpo_json(self) -> dict[str, Any]:
        return {
            "bytes_transferidos": self.bytes_transferidos,
            "concluido": self.concluido,
        }

    @classmethod
    def _corpo_de_json(cls, dados: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "bytes_transferidos": _exigir_inteiro(dados, "bytes_transferidos"),
            "concluido": _exigir_bool(dados, "concluido"),
        }


@dataclass(frozen=True)
class ResultadoDeInventario(Resultado):
    TIPO = "inventario"

    job_em_curso: bool
    nomes_encontrados: tuple[str, ...]

    def _corpo_json(self) -> dict[str, Any]:
        return {
            "job_em_curso": self.job_em_curso,
            "nomes_encontrados": list(self.nomes_encontrados),
        }

    @classmethod
    def _corpo_de_json(cls, dados: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "job_em_curso": _exigir_bool(dados, "job_em_curso"),
            "nomes_encontrados": _exigir_lista_de_texto(dados, "nomes_encontrados"),
        }


@dataclass(frozen=True)
class ResultadoDeLocalizacao(Resultado):
    """Onde o Nova diz que a VM esta."""

    TIPO = "localizacao"

    no_atual: str

    def _corpo_json(self) -> dict[str, Any]:
        return {"no_atual": self.no_atual}

    @classmethod
    def _corpo_de_json(cls, dados: Mapping[str, Any]) -> dict[str, Any]:
        return {"no_atual": _exigir_texto(dados, "no_atual")}


# ── Conversao de corpo ─────────────────────────────────────────

# Efeito e resultado sao convertidos e CONFERIDOS pelos mesmos auxiliares. Copiar
# cru produzia um caso concreto e ruim: `{"sucesso": "false"}` virava a string
# "false", que e verdadeira em Python, e um efeito que falhou era absorvido como
# sucesso. Com `concluido`, o mesmo vira janela dada por copiada sem ter sido —
# o defeito que o ciclo_id existe para impedir, entrando por outra porta.
#
# A leitura e simetrica a escrita: cada tipo diz como se le, do lado de como se
# escreve. Reflexao sobre as anotacoes seria mais curta e leria `Optional[str]` e
# `tuple[str, ...]` como objetos de `typing`, nao como classes — e o proximo tipo
# composto silenciaria de novo.


def _exigir(dados: Mapping[str, Any], nome: str) -> Any:
    if nome not in dados:
        raise ValorDesconhecidoError(f"sem o campo obrigatorio {nome!r}")
    return dados[nome]


def _exigir_bool(dados: Mapping[str, Any], nome: str) -> bool:
    valor = _exigir(dados, nome)
    if not isinstance(valor, bool):
        raise ValorDesconhecidoError(
            f"{nome!r} tem que ser booleano, e veio {valor!r} ({type(valor).__name__}). "
            'Texto nao vira booleano por conveniencia: "false" e verdadeiro.'
        )
    return valor


def _exigir_inteiro(dados: Mapping[str, Any], nome: str) -> int:
    valor = _exigir(dados, nome)
    # `isinstance(True, int)` e verdadeiro em Python, entao booleano precisa ser
    # recusado a mao — senao `True` entra como 1 na telemetria.
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValorDesconhecidoError(
            f"{nome!r} tem que ser inteiro, e veio {valor!r} ({type(valor).__name__}). "
            "Numero em texto quebra a soma depois, longe daqui."
        )
    return valor


def _exigir_uuid(dados: Mapping[str, Any], nome: str) -> UUID:
    """UUID em texto, e so em texto.

    `UUID(str(...))` ja falhava fechado para lixo, mas com `ValueError` cru — e
    quem trata "contrato mais novo que eu" devolvendo o efeito a fila pega
    `ValorDesconhecidoError`, nao `ValueError`. Falha fechada com o tipo errado
    vira excecao nao tratada no despachante.
    """
    valor = _exigir(dados, nome)
    if not isinstance(valor, str):
        raise ValorDesconhecidoError(f"{nome!r} tem que ser UUID em texto, e veio {valor!r}")
    try:
        return UUID(valor)
    except ValueError as erro:
        raise ValorDesconhecidoError(f"{nome!r} nao e UUID: {valor!r}") from erro


def _exigir_mapa(dados: Mapping[str, Any], nome: str) -> Mapping[str, Any]:
    valor = _exigir(dados, nome)
    if not isinstance(valor, Mapping):
        raise ValorDesconhecidoError(f"{nome!r} tem que ser objeto, e veio {valor!r}")
    return valor


def _exigir_texto(dados: Mapping[str, Any], nome: str) -> str:
    valor = _exigir(dados, nome)
    if not isinstance(valor, str):
        raise ValorDesconhecidoError(f"{nome!r} tem que ser texto, e veio {valor!r}")
    return valor


def _texto_ou_nada(dados: Mapping[str, Any], nome: str) -> Optional[str]:
    valor = dados.get(nome)
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ValorDesconhecidoError(f"{nome!r} tem que ser texto ou nada, e veio {valor!r}")
    return valor


def _exigir_lista_de_texto(dados: Mapping[str, Any], nome: str) -> tuple[str, ...]:
    valor = _exigir(dados, nome)
    if isinstance(valor, str) or not isinstance(valor, (list, tuple)):
        raise ValorDesconhecidoError(f"{nome!r} tem que ser lista de texto, e veio {valor!r}")
    for item in valor:
        if not isinstance(item, str):
            raise ValorDesconhecidoError(f"{nome!r} tem item que nao e texto: {item!r}")
    return tuple(valor)


# ── Leitura ─────────────────────────────────────────────────────────────────

T = TypeVar("T")


def _por_tipo(raiz: type[T]) -> dict[str, type[T]]:
    """Catalogo de subclasses por `TIPO`.

    Duas coisas valem estar escritas.

    `TIPO` repetido LEVANTA. A ultima classe visitada venceria em silencio, e a
    ordem de visita vem de `pop()` sobre `__subclasses__()` — nao e estavel nem
    previsivel. Com duas classes disputando a mesma string, `efeito_de_json`
    construiria o tipo errado a partir de um JSON valido, sem erro em lugar
    nenhum. Ambiguidade e falha, nao escolha silenciosa.

    E o catalogo so enxerga classe **ja importada**. Hoje tudo mora num modulo e
    isso nao morde; no dia em que um efeito nascer noutro modulo, ele sera
    recusado como "tipo desconhecido" ate alguem importa-lo. A falha e fechada,
    entao e segura — mas o sintoma nao sugere a causa, e por isso esta aqui.
    """
    achados: dict[str, type[T]] = {}
    pendentes = list(raiz.__subclasses__())
    while pendentes:
        classe = pendentes.pop()
        pendentes.extend(classe.__subclasses__())
        tipo = classe.__dict__.get("TIPO")
        if not isinstance(tipo, str):
            continue
        anterior = achados.get(tipo)
        if anterior is not None:
            raise ValorDesconhecidoError(
                f"TIPO {tipo!r} declarado por duas classes: "
                f"{anterior.__name__} e {classe.__name__}. Uma delas venceria "
                "conforme a ordem de visita, que nao e estavel."
            )
        achados[tipo] = classe
    return achados


def _campos(classe: type) -> dict[str, Any]:
    return {campo.name: campo for campo in fields(classe)}


def efeito_de_json(dados: Mapping[str, Any]) -> Efeito:
    """Le um efeito. Campo desconhecido se ignora; valor desconhecido recusa."""
    catalogo = _por_tipo(Efeito)
    tipo = dados.get("tipo")
    if tipo not in catalogo:
        raise ValorDesconhecidoError(
            f"tipo de efeito desconhecido: {tipo!r}. Esta versao conhece "
            f"{sorted(catalogo)}. Devolva o efeito a fila em vez de adivinhar."
        )
    classe = catalogo[str(tipo)]

    alvo_cru = dados.get("alvo")
    try:
        alvo = Alvo(alvo_cru)
    except ValueError as erro:
        raise ValorDesconhecidoError(
            f"alvo desconhecido: {alvo_cru!r}. Cair num padrao aqui e rotear "
            "errado, que e o defeito que o Alvo existe para impedir."
        ) from erro
    if alvo is not classe.ALVO:
        raise ValorDesconhecidoError(
            f"{classe.TIPO!r} declara alvo {classe.ALVO.value!r}, e o efeito "
            f"chegou com {alvo.value!r}. Contradicao nao se resolve escolhendo um."
        )

    argumentos: dict[str, Any] = {
        "tenant_id": _exigir_uuid(dados, "tenant_id"),
        "ciclo_id": _exigir_uuid(dados, "ciclo_id"),
    }
    nomes = _campos(classe)
    if "vm_id" in nomes:
        chave = ChaveDeExclusao.de_json(_exigir_mapa(dados, "chave_de_exclusao"))
        argumentos["vm_id"] = chave.vm_id
        argumentos["disco"] = chave.disco
    return classe(**argumentos)


def resultado_de_json(dados: Mapping[str, Any]) -> Resultado:
    """Le um resultado. Mesma regra: campo se ignora, valor recusa."""
    catalogo = _por_tipo(Resultado)
    tipo = dados.get("tipo")
    if tipo not in catalogo:
        raise ValorDesconhecidoError(
            f"tipo de resultado desconhecido: {tipo!r}. Esta versao conhece {sorted(catalogo)}."
        )
    classe = catalogo[str(tipo)]
    chave_crua = dados.get("chave")
    argumentos: dict[str, Any] = {
        "tenant_id": _exigir_uuid(dados, "tenant_id"),
        "ciclo_id": _exigir_uuid(dados, "ciclo_id"),
        "tipo_do_efeito": _exigir_texto(dados, "tipo_do_efeito"),
        "chave": None
        if chave_crua is None
        else ChaveDeExclusao.de_json(_exigir_mapa(dados, "chave")),
    }
    argumentos.update(classe._corpo_de_json(dados))
    return classe(**argumentos)
