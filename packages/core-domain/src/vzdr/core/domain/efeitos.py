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
        return cls(vm_id=UUID(str(dados["vm_id"])), disco=str(dados["disco"]))


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
    dizer a mesma coisa. Dois efeitos do mesmo tipo, do mesmo ciclo, sobre o mesmo
    disco nao podem estar pendentes juntos: e o que a chave de exclusao garante.

    `tenant_id` esta aqui pelo mesmo motivo que esta no efeito: o resultado
    atravessa a mesma fila e a mesma tabela sob RLS, e quem isola nao deveria
    precisar abri-lo. A varredura falava de efeito; a primeira linha dela vale
    para os dois, e esta escrito em vez de deduzido.
    """

    TIPO: ClassVar[str]

    tenant_id: UUID
    ciclo_id: UUID
    tipo_do_efeito: str
    chave: Optional[ChaveDeExclusao] = None

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


@dataclass(frozen=True)
class ResultadoSimples(Resultado):
    """Deu certo, ou nao deu, sem mais nada a dizer."""

    TIPO = "simples"

    sucesso: bool = True
    motivo: Optional[str] = None

    def _corpo_json(self) -> dict[str, Any]:
        return {"sucesso": self.sucesso, "motivo": self.motivo}


@dataclass(frozen=True)
class ResultadoDeCopia(Resultado):
    TIPO = "copia"

    bytes_transferidos: int = 0
    concluido: bool = False

    def _corpo_json(self) -> dict[str, Any]:
        return {
            "bytes_transferidos": self.bytes_transferidos,
            "concluido": self.concluido,
        }


@dataclass(frozen=True)
class ResultadoDeInventario(Resultado):
    TIPO = "inventario"

    job_em_curso: bool = False
    nomes_encontrados: tuple[str, ...] = ()

    def _corpo_json(self) -> dict[str, Any]:
        return {
            "job_em_curso": self.job_em_curso,
            "nomes_encontrados": list(self.nomes_encontrados),
        }


@dataclass(frozen=True)
class ResultadoDeLocalizacao(Resultado):
    """Onde o Nova diz que a VM esta."""

    TIPO = "localizacao"

    no_atual: str = ""

    def _corpo_json(self) -> dict[str, Any]:
        return {"no_atual": self.no_atual}


# ── Leitura ─────────────────────────────────────────────────────────────────

T = TypeVar("T")


def _por_tipo(raiz: type[T]) -> dict[str, type[T]]:
    achados: dict[str, type[T]] = {}
    pendentes = list(raiz.__subclasses__())
    while pendentes:
        classe = pendentes.pop()
        pendentes.extend(classe.__subclasses__())
        tipo = classe.__dict__.get("TIPO")
        if isinstance(tipo, str):
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
        "tenant_id": UUID(str(dados["tenant_id"])),
        "ciclo_id": UUID(str(dados["ciclo_id"])),
    }
    nomes = _campos(classe)
    if "vm_id" in nomes:
        chave = ChaveDeExclusao.de_json(dados["chave_de_exclusao"])
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
    argumentos: dict[str, Any] = {
        "tenant_id": UUID(str(dados["tenant_id"])),
        "ciclo_id": UUID(str(dados["ciclo_id"])),
        "tipo_do_efeito": str(dados["tipo_do_efeito"]),
    }
    if dados.get("chave") is not None:
        argumentos["chave"] = ChaveDeExclusao.de_json(dados["chave"])
    for nome in _campos(classe):
        if nome in argumentos or nome == "chave":
            continue
        if nome in dados:
            argumentos[nome] = dados[nome]
    if "nomes_encontrados" in argumentos:
        argumentos["nomes_encontrados"] = tuple(argumentos["nomes_encontrados"])
    return classe(**argumentos)
