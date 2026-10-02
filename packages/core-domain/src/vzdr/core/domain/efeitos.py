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
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Optional, TypeVar
from uuid import UUID

__all__ = [
    "PREEMPCAO_DESPEJA_DETENTOR",
    "Alvo",
    "CercarDestino",
    "CatalogoAmbiguoError",
    "DiscoNoInventario",
    "EstadoDoBitmap",
    "FonteIncoerenteError",
    "ImagemNoInventario",
    "ChaveDeExclusao",
    "ConfirmarNoDestino",
    "ConsultarNoDaVm",
    "DescartarBitmap",
    "Efeito",
    "EfeitoDeDisco",
    "EfeitoDePreempcao",
    "EfeitoDeVm",
    "FecharJanela",
    "IniciarCopia",
    "InventariarVm",
    "PublicarExport",
    "RegistrarPontoDeRecuperacao",
    "RegistroMalformadoError",
    "Resultado",
    "RemoverCheckpointsAnteriores",
    "ResultadoDeCopia",
    "ResultadoDeInventario",
    "ResultadoDeLocalizacao",
    "ResultadoSimples",
    "ResultadoVmAusente",
    "RetirarExport",
    "ValorDesconhecidoError",
    "efeito_de_json",
    "pode_tomar_chave_tomada",
    "chaves_de",
    "responde_a",
    "resultado_de_json",
    "se_excluem",
]


class ValorDesconhecidoError(ValueError):
    """Valor que esta versao nao interpreta, num campo que carrega regra:
    REENVIAR e alarmar — "contrato mais novo que eu".

    Sao tres casos, e so eles: tipo de efeito, tipo de resultado e alvo que esta
    versao nao conhece. Registro quebrado nao e isto, e levanta
    `RegistroMalformadoError`, que pede a acao contraria.

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


class RegistroMalformadoError(ValueError):
    """Registro quebrado: DESCARTAR e alarmar. Nunca reenviar.

    Campo ausente, tipo errado, UUID que nao e UUID, chave repetida, efeito de
    disco com duas chaves, alvo que contradiz o tipo, efeito de VM sem disco. Nada
    disso e "contrato mais novo": a evolucao do contrato e aditiva e nunca remove
    campo nem muda significado de campo existente (ADR-0015), entao nenhuma versao
    futura manda isto.

    Existe separado de `ValorDesconhecidoError` porque o TIPO da excecao e o que
    decide a acao de quem trata, e as duas acoes sao opostas. Reenviar um registro
    quebrado e devolve-lo a fila para sempre — o laco que nao termina, com outra
    roupa.
    """


# **Nunca `except ValueError:` no caminho de despacho.** ValorDesconhecidoError e
# RegistroMalformadoError herdam as duas de ValueError, e um `except` pelo
# ancestral captura as duas — que pedem acoes opostas, reenviar e descartar. O
# teste de que nenhuma herda da outra e necessario e nao suficiente. O remedio
# nao e aqui: herdar de Exception direto perderia a informacao de que sao erro de
# valor. E regra de quem despacha, na fila do core-003 e no protocolo do agente.


class CatalogoAmbiguoError(RuntimeError):
    """Defeito DESTA VERSAO do codigo, e nao da mensagem: parar e aparecer.

    Duas classes declarando o mesmo `TIPO`. Reenviar a mensagem entraria em laco,
    e descarta-la jogaria fora registro valido. Nao e dela o defeito.
    """


class FonteIncoerenteError(RuntimeError):
    """A fonte EXTERNA violou uma invariante que ela mesma documenta: PARAR e
    escalar para o fornecedor. Nunca reenviar, nunca descartar.

    O caso que a criou: o QEMU documenta que `inconsistent` "implies persistent to
    be true; recording and busy to be false". Um bitmap que chegue `inconsistent`
    e `recording` ao mesmo tempo nao e registro quebrado nem contrato mais novo — e
    o fork da plataforma desobedecendo a propria invariante, e entao a confianca
    nesses campos cai em todo o parque.

    E um quarto tipo, e nao o `CatalogoAmbiguoError`, pela ACAO de quem trata, que
    e o criterio dos tres: aquele manda parar e consertar o NOSSO codigo; este
    manda parar e levar a plataforma ao fornecedor. Reenviar voltaria igual;
    descartar jogaria fora o unico sinal de que o fork nao e confiavel.
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
    #: Entrou quando o primeiro efeito passou a usa-lo: o snapshot Cinder que E o
    #: ponto de recuperacao e chamada a API da nuvem de destino. Antes, o plano dizia
    #: que nenhum efeito da v1 o usava — e o ciclo nao tinha como terminar.
    #:
    #: Valor novo de enumeracao e ADITIVO: chega numa versao antiga como
    #: `ValorDesconhecidoError`, que pede reenvio — o caminho desenhado. Nao e
    #: afrouxar campo existente, que o ADR-0015 proibe.
    API_DA_NUVEM_DE_DESTINO = "api_da_nuvem_de_destino"


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
    #: O SUJEITO: sobre qual VM o efeito e. Todo efeito tem um, e dize-lo nao pode
    #: depender de quem executa. A varredura perguntou o que o despachante precisa
    #: ler e nunca perguntou se o efeito tem sujeito — e dois efeitos de leitura
    #: nasceram sem: um inventario que nao dizia de onde e uma consulta que nao
    #: dizia de quem. Um ciclo e de uma VM so, entao isto e a VM do ciclo.
    #:
    #: Nao e referencia de onde derivar tenant no sentido da regra acima: e o
    #: recurso sobre o qual se age. O risco de oraculo que a regra protege fica
    #: com quem guardar efeitos: chave estrangeira COMPOSTA (tenant_id, vm_id), o
    #: padrao da core-001, e nunca so vm_id.
    vm_id: UUID
    #: Em qual no o efeito roda — so para efeito de agente, e obrigatorio nele.
    #:
    #: O `Alvo` diz que dois efeitos tem o mesmo alvo quando falham juntos, e os
    #: agentes de dois nos falham separado: "agente de origem" sem o no nao e um
    #: alvo, sao varios. Deixar o despachante resolver o no a partir do vm_id
    #: seria ler fora do envelope — e, na reconciliacao, resolver e exatamente o
    #: que esta em duvida depois de uma migracao. Entao o no vem DECLARADO, com
    #: procedencia (a ultima localizacao que o Nova informou), e e CONFERIDO na
    #: resposta: resultado de no diferente nao responde.
    no: Optional[str]

    def __post_init__(self) -> None:
        exige_no = self.ALVO is Alvo.AGENTE_DE_ORIGEM
        if exige_no and not _no_valido(self.no):
            raise RegistroMalformadoError(
                f"{type(self).__name__} roda num agente e precisa dizer em qual no: {self.no!r}"
            )
        if not exige_no and self.no is not None:
            raise RegistroMalformadoError(
                f"{type(self).__name__} nao roda num agente, e nao leva no: {self.no!r}"
            )

    @property
    def alvo(self) -> Alvo:
        return self.ALVO

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "tipo": self.TIPO,
            "tenant_id": str(self.tenant_id),
            "ciclo_id": str(self.ciclo_id),
            "vm_id": str(self.vm_id),
            "no": self.no,
            "alvo": self.ALVO.value,
        }
        dados.update(self._corpo_json())
        return dados

    def _corpo_json(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class EfeitoDeDisco(Efeito):
    """Efeito que toca UM disco, e por isso segura uma chave de exclusao."""

    disco: str

    def chaves_de_exclusao(self) -> tuple[ChaveDeExclusao, ...]:
        """Uma so, e ainda assim no plural — o envelope e o mesmo para todos.

        Deterministica: mesmo disco, mesma chave, em qualquer ciclo. Nao entra o
        `ciclo_id` de proposito: se entrasse, dois ciclos sobre o mesmo disco
        teriam chaves diferentes e poderiam escrever juntos.
        """
        return (ChaveDeExclusao(vm_id=self.vm_id, disco=self.disco),)

    def _corpo_json(self) -> dict[str, Any]:
        return {"chaves_de_exclusao": [c.para_json() for c in self.chaves_de_exclusao()]}


@dataclass(frozen=True)
class EfeitoDeVm(Efeito):
    """Efeito que age em TODOS os discos da VM de uma vez, como unidade.

    Existe porque a varredura do envelope perguntou o que a fila le, e nao de
    quantos discos. Checkpoint e congelamento sao da VM: feitos disco a disco, cada
    disco teria um instante diferente, e com banco num disco e log noutro o ponto
    de recuperacao pareceria valido e nao seria — sem erro em lugar nenhum,
    aparecendo so no restore.

    Segura UMA CHAVE POR DISCO. A fila concede o lease so se todas estiverem
    livres, de uma vez: adquirir chave por chave abriria espaco para dois efeitos
    segurando metades e esperando um pelo outro.
    """

    discos: tuple[str, ...]

    def __post_init__(self) -> None:
        # Chama a base: sobrescrever __post_init__ sem isso apaga a conferencia do
        # no em silencio — o risco que o teste sobre o catalogo inteiro vigia.
        super().__post_init__()
        if not self.discos:
            raise RegistroMalformadoError(f"{type(self).__name__} sem disco nenhum nao age em nada")
        if len(set(self.discos)) != len(self.discos):
            raise RegistroMalformadoError(
                f"{type(self).__name__} com disco repetido: {self.discos}"
            )
        # ORDEM CANONICA. Sem ela, `("vda", "vdb")` e `("vdb", "vda")` seriam
        # valores diferentes com o mesmo conjunto de chaves, e tres coisas
        # quebrariam em silencio: a fila deixaria de desduplicar pedido igual, o
        # resultado deixaria de correlacionar por igualdade, e a ida e volta pelo
        # JSON construiria outro objeto. E alcancavel: a maquina monta a lista a
        # partir da VM, e a reconciliacao a partir do inventario do hypervisor.
        object.__setattr__(self, "discos", tuple(sorted(self.discos)))

    def chaves_de_exclusao(self) -> tuple[ChaveDeExclusao, ...]:
        return tuple(ChaveDeExclusao(vm_id=self.vm_id, disco=d) for d in self.discos)

    def _corpo_json(self) -> dict[str, Any]:
        return {"chaves_de_exclusao": [c.para_json() for c in self.chaves_de_exclusao()]}


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


def chaves_de(efeito: Efeito) -> tuple[ChaveDeExclusao, ...]:
    """As chaves que o efeito segura — nenhuma, se ele nao toca disco."""
    if isinstance(efeito, (EfeitoDeDisco, EfeitoDeVm)):
        return efeito.chaves_de_exclusao()
    return ()


#: Nome de no como o VHI o mostra: letras, digitos, ponto, hifen e sublinhado.
_NO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _no_valido(no: Optional[str]) -> bool:
    return isinstance(no, str) and _NO.fullmatch(no) is not None


def _ordem_da_chave(chave: ChaveDeExclusao) -> tuple[str, str]:
    return (str(chave.vm_id), chave.disco)


def se_excluem(a: Efeito, b: Efeito) -> bool:
    """Dois efeitos se excluem quando as chaves deles SE INTERSECTAM.

    Nao "quando tem a mesma chave". Com chave no plural, "mesma" passa a ser lida
    como "conjuntos identicos", e ai um efeito de VM sobre `vda, vdb, vdc` e um
    efeito de disco sobre `vdb` conviveriam — o defeito voltando pela porta da
    generalizacao. Um disco em comum basta.

    Isto e a regra; quem pode agir APESAR dela e outra pergunta, respondida por
    `pode_tomar_chave_tomada`.
    """
    return bool(set(chaves_de(a)) & set(chaves_de(b)))


# ── Os efeitos ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FecharJanela(EfeitoDeVm):
    """Fecha a janela corrente e abre a proxima, numa unidade so.

    Sao dois passos na descricao — congelar a janela acumulada num bitmap
    temporario, e criar o checkpoint que passa a acumular a proxima — e UM na
    execucao. A pergunta que decide nao e quantos passos a prosa descreve: e se
    existe um instante entre os dois em que uma escrita se perde. Existe. Uma
    escrita que chegue entre o congelamento e o checkpoint cai no bitmap velho,
    que ja foi mesclado e nao sera lido de novo, e nao cai no novo, que ainda nao
    existe. Some das duas contabilidades: nenhum erro, um bloco a menos no
    espelho. E por isso que o backup incremental do QEMU faz as duas coisas numa
    `transaction` so, e o laboratorio ja usava `transaction` para a mescla.

    O onus da prova fica invertido: um efeito ate a medicao provar que da para
    separar. Separar depois e facil; descobrir a perda em producao nao tem volta.

    E da VM, e nao do disco, pelo mesmo motivo por outro lado: checkpoint por
    disco daria um instante por disco.

    Antes havia `CriarCheckpoint`, efeito de disco, e nenhum efeito criava o
    bitmap temporario — embora `DescartarBitmap` o removesse.
    """

    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "fechar_janela"


@dataclass(frozen=True)
class IniciarCopia(EfeitoDeDisco):
    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "iniciar_copia"


@dataclass(frozen=True)
class DescartarBitmap(EfeitoDeDisco):
    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "descartar_bitmap"


@dataclass(frozen=True)
class InventariarVm(Efeito):
    """A fotografia do que existe DA VM no no indicado: nomes nossos, job em curso.

    Da VM, e nao "do hypervisor". A versao anterior se chamava
    InventariarHypervisor e nao dizia qual; pedir "o hypervisor onde a VM esta"
    pressupoe saber onde ela esta, que e justamente o que esta em duvida depois de
    uma migracao. O no vem declarado no envelope, com a procedencia da ultima
    consulta ao Nova, e a resposta de outro no nao responde.

    Nunca pedida ao detentor do lease: ele e justamente quem nao responde no
    cenario que a reconciliacao existe para cobrir.

    **O vm_id aqui NAO e chave de exclusao, e isto e deliberado.** Com chave, o
    inventario so rodaria com o lease livre — e o lease esta preso pela copia
    zumbi que e a razao de o inventario existir. Deadlock. Nao se resolve com
    preempcao: preempcao retira capacidade de escrever, e uma leitura nao retira
    nada de ninguem; ela simplesmente nao precisa de exclusividade.

    Se a VM nao estiver no no, a resposta e `ResultadoVmAusente` — nunca um
    inventario vazio, que seria verdade sobre o no e mentira sobre a VM.
    """

    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "inventariar_vm"


@dataclass(frozen=True)
class ConsultarNoDaVm(Efeito):
    """Em que no a VM esta agora — pelo Nova, nao pelo agente.

    E a segunda forma de evidencia: se a VM nao esta mais no no gravado, o
    escritor era o processo QEMU do no antigo e nao existe mais. Sem ela, um no
    morto bloqueia aquele disco para sempre, porque nao ha quem responda o
    inventario.

    Por isso o alvo e a API da nuvem, e nao o agente: sao modos de falha
    diferentes, e este efeito existe para o caso em que o outro nao chega.

    A VM consultada e o `vm_id` do envelope — a versao anterior nao dizia de qual
    VM era. E, como no inventario, ele NAO e chave de exclusao: esta consulta
    existe para o caso em que o disco esta preso por um zumbi.
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
class RegistrarPontoDeRecuperacao(EfeitoDeVm):
    """O snapshot Cinder dos espelhos — o ponto de recuperacao.

    Faltava. O ciclo da arquitetura termina em "snapshot Cinder", e nenhum efeito o
    executava: a maquina podia copiar e confirmar, e nunca produzir um ponto.

    De VM, e nao de disco, pelo P5: o ponto e da VM inteira, com todos os volumes do
    mesmo ciclo. E segura as chaves de todos os discos: snapshot do espelho enquanto
    uma copia zumbi escreve nele produziria um ponto inconsistente, sem erro em
    lugar nenhum. A maquina so o pede depois de confirmados todos os discos.
    """

    ALVO = Alvo.API_DA_NUVEM_DE_DESTINO
    TIPO = "registrar_ponto_de_recuperacao"


@dataclass(frozen=True)
class RetirarExport(EfeitoDeDisco):
    """Retira o export do ciclo, no fim do caminho normal.

    Faltava, e a falta desmentia uma frase nossa: "export fechado entre ciclos deixa
    o espelho gravavel pela rede so durante a janela de copia". Sem efeito que o
    retirasse, o export ficava aberto depois do ciclo.

    NAO e o `CercarDestino`. Cercar e preempcao: toma chave ja tomada e usa
    `mode: hard` contra um escritor que pode estar vivo. Retirar e a saida normal,
    com chave normal, depois da copia confirmada. Reusar um para o outro misturaria
    as obrigacoes da categoria.

    **Idempotente, e pelo motivo proprio, nao por ser parecido com o cercamento.**
    O estado desejado e AUSENCIA do export. Retirada repetida de export ja retirado
    encontra o estado desejado, e isso e sucesso. A idempotencia nao vem da
    categoria preempcao: e obrigacao de todo efeito de limpeza.
    """

    ALVO = Alvo.RECEPTORA
    TIPO = "retirar_export"


@dataclass(frozen=True)
class RemoverCheckpointsAnteriores(EfeitoDeVm):
    """Mantem so o checkpoint deste ciclo, e remove os nossos anteriores.

    Faltava: o ciclo termina em "apaga checkpoint anterior", e nada o apagava. Sem
    isso cada ciclo deixaria um checkpoint, e cada checkpoint retem um bitmap.

    A forma e "mantenha so o do ciclo corrente", e nao "remova o do ciclo X", e o
    motivo e correlacao. As janelas pendentes se consolidam: depois de ciclos que
    falharam, um ciclo bem-sucedido libera VARIOS checkpoints. Com um efeito por
    checkpoint, todos teriam o mesmo ciclo, o mesmo tipo e as mesmas chaves, e a
    resposta de um responderia ao outro. Com "mantenha so o corrente", e um por
    ciclo, e o nome a manter sai do `ciclo_id` do envelope.

    E isso torna IMPOSSIVEL DE EXPRESSAR o erro mais grave da classe P2: apagar o
    checkpoint do ciclo corrente, que e a janela que o `FecharJanela` acabou de
    abrir. Nao ha campo onde escrever esse ciclo.

    Remove so o que `ler_nome` le como `NomeDeCiclo` de checkpoint. Nome nosso
    ilegivel — de uma versao mais nova — nunca e tocado.

    Idempotente: o estado desejado e a ausencia dos anteriores. A maquina so o pede
    depois de confirmados os discos e registrado o ponto — e ai que o P2 vive.

    O AGENTE O EXECUTA PELA API DE CHECKPOINT DO LIBVIRT, e nunca por
    `block-dirty-bitmap-remove` no monitor. O proprio libvirt documenta, em
    `virDomainQemuMonitorCommand`: "A @cmd that alters state that is also tracked
    by libvirt is unsafe". O bitmap de um checkpoint e estado que o libvirt
    rastreia; remove-lo por baixo deixa o metadado de checkpoint apontando para um
    bitmap que nao existe — a familia do "Bitmap already exists". Ler pelo monitor
    e seguro; escrever, nao.
    """

    ALVO = Alvo.AGENTE_DE_ORIGEM
    TIPO = "remover_checkpoints_anteriores"


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
    - **sem chave** — `InventariarVm` e `ConsultarNoDaVm` nao tem chave nenhuma,
      e nada impede dois pendentes.

    Na preempcao, a correlacao e inofensiva **porque a absorcao e idempotente**, e
    isso e obrigacao e nao coincidencia. No dia em que existir uma preempcao que
    nao seja idempotente, esta e a linha que reprova a ideia.

    Na classe sem chave, idempotencia cobre a repeticao e NAO cobre a resposta
    errada — e o que a garante e o SUJEITO e o NO. Houve uma versao em que o
    inventario nao dizia de onde, a consulta nao dizia de quem, e os resultados
    nao diziam quem respondeu: um inventario respondido pelo agente de outro no
    voltava vazio, a reconciliacao lia "nao ha orfao", e o orfao ficava. Uma versao
    ainda anterior deste texto dizia que a classe era segura; nao era. Hoje
    `responde_a` compara sujeito e no, e "a VM nao esta aqui" e `ResultadoVmAusente`.

    **Correlacao e IGUALDADE do conjunto de chaves; exclusao e INTERSECAO.** O
    mesmo campo tem duas relacoes, e confundi-las e o erro facil: `se_excluem`
    existe e esta pronta, e usada para correlacionar faria um resultado de
    `FecharJanela` sobre `vda, vdb` casar com um `IniciarCopia` sobre `vdb`. Para
    correlacionar existe `responde_a`. E e por causa da igualdade que a ordem
    canonica das chaves nao e estetica.

    `tenant_id` esta aqui pelo mesmo motivo que esta no efeito: o resultado
    atravessa a mesma fila e a mesma tabela sob RLS, e quem isola nao deveria
    precisar abri-lo. A varredura falava de efeito; a primeira linha dela vale
    para os dois, e esta escrito em vez de deduzido.
    """

    TIPO: ClassVar[str]

    tenant_id: UUID
    ciclo_id: UUID
    tipo_do_efeito: str
    #: As mesmas chaves do efeito que este resultado responde — no plural, como
    #: no efeito. Sem padrao: quem nao tem chave passa `()` explicitamente. Com
    #: padrao aqui, toda subclasse seria obrigada a ter padrao tambem — e ai
    #: `sucesso` e `concluido` ganhariam um, e silencio significaria sucesso.
    chaves: tuple[ChaveDeExclusao, ...]
    #: O sujeito do efeito respondido. As chaves eram um PROXY da identidade do
    #: efeito, e para a classe sem chave o proxy e vazio: dois ConsultarNoDaVm de
    #: VMs diferentes correlacionariam um com o outro. O sujeito diz de quem e.
    vm_id: UUID
    #: Quem respondeu, quando foi um agente. `responde_a` confere com o no que o
    #: efeito declarou: o agente de outro no nao responde por este.
    no_que_respondeu: Optional[str]

    def __post_init__(self) -> None:
        # A mesma recusa que a leitura do JSON ja fazia: dois caminhos que fazem o
        # mesmo trabalho, e nenhum deles e o frouxo.
        if len(set(self.chaves)) != len(self.chaves):
            raise RegistroMalformadoError(f"resultado com chave repetida: {self.chaves}")
        # As chaves sao da VM do sujeito. Chave de outra VM — ou de duas — faria o
        # resultado nunca responder a nada, e o efeito ficaria pendente para sempre
        # esperando resposta que ja chegou e foi ignorada. Isto substitui o "zero ou
        # uma VM" anterior, que o sujeito tornou mais forte.
        alheias = {c.vm_id for c in self.chaves} - {self.vm_id}
        if alheias:
            raise RegistroMalformadoError(
                f"resultado com chaves de VMs diferentes do sujeito {self.vm_id}: "
                f"{sorted(map(str, alheias))}"
            )
        if self.no_que_respondeu is not None and not _no_valido(self.no_que_respondeu):
            raise RegistroMalformadoError(f"no_que_respondeu invalido: {self.no_que_respondeu!r}")
        # O MESMO PAREAMENTO que o efeito confere, do lado do resultado. Sem isto,
        # `ResultadoSimples(tipo_do_efeito="confirmar_no_destino", no_que_respondeu=
        # "no-01")` seria construtivel e nunca responderia a nada — o efeito de
        # receptora tem `no` None. E o efeito pendurado seria um ConfirmarNoDestino:
        # pela P2 a janela nao e liberada, o ciclo trava e o checkpoint nao sai.
        #
        # So quando o tipo e CONHECIDO. Tipo desconhecido e contrato mais novo, e
        # recusar como malformado descartaria o que deveria ser reenviado.
        classe = _por_tipo(Efeito).get(self.tipo_do_efeito)
        if classe is not None:
            de_agente = classe.ALVO is Alvo.AGENTE_DE_ORIGEM
            if de_agente and self.no_que_respondeu is None:
                raise RegistroMalformadoError(
                    f"resposta a {self.tipo_do_efeito!r}, que roda num agente, sem dizer qual no"
                )
            if not de_agente and self.no_que_respondeu is not None:
                raise RegistroMalformadoError(
                    f"resposta a {self.tipo_do_efeito!r}, que nao roda num agente, "
                    f"dizendo no {self.no_que_respondeu!r}"
                )
        # Ordem canonica, pelo mesmo motivo do EfeitoDeVm: a correlacao e por
        # IGUALDADE, e igualdade de tupla depende de ordem.
        object.__setattr__(self, "chaves", tuple(sorted(self.chaves, key=_ordem_da_chave)))

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "tipo": self.TIPO,
            "tenant_id": str(self.tenant_id),
            "ciclo_id": str(self.ciclo_id),
            "tipo_do_efeito": self.tipo_do_efeito,
            "vm_id": str(self.vm_id),
            "no_que_respondeu": self.no_que_respondeu,
        }
        dados["chaves"] = [c.para_json() for c in self.chaves]
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
class EstadoDoBitmap:
    """Um bitmap, como o `query-block` o mostra — o que as seis condicoes do
    ADR-0016 leem.

    OS NOMES DOS CAMPOS SAO OS DO QEMU, de proposito: o agente copia, nao traduz, e
    traducao e onde dois nomes da mesma coisa discordam.

    `inconsistent` e OBRIGATORIO aqui, e no QEMU e opcional — so e impresso quando
    verdadeiro. Herdar a opcionalidade criaria o primeiro campo cuja AUSENCIA
    carrega significado vindo de fora, e a regra do contrato e "campo desconhecido
    se ignora": um agente antigo ou com defeito que nao mandasse o campo seria lido
    como "consistente", isto e, "pode confiar". Falha aberta, na pior direcao. Quem
    normaliza ausente -> falso e o AGENTE, na borda, onde tem o JSON do QEMU na mao
    e sabe que a ausencia veio do QEMU. Aqui, silencio nao significa "esta tudo bem".

    A invariante documentada do QEMU — inconsistente implica persistente, e nem
    gravando nem ocupado — e conferida na construcao. Violada, e
    `FonteIncoerenteError`: o fork nao e confiavel nesses campos. E por ela, tambem,
    que `recording` falso alcanca todo inconsistente: `recording` e o teste mais
    amplo, e `inconsistent` diz o MOTIVO — desabilitado pode ter conserto;
    inconsistente sai e vira resync.

    ARMADILHA: o `dirty-flag` do qcow2 NAO e dirty bitmap. E o bit de sujo da
    imagem, par do `lazy-refcounts`, e vem verdadeiro em toda VM ligada. Le-lo como
    estado do bitmap e o engano do `dirty-bitmaps: state false` — que ja custou um
    chamado — pela mesma porta.
    """

    nome: str
    granularity: int
    #: Bytes sujos, ANTES de copiar. Entrada do limiar e do ETA (ADR-0016, decisao 4).
    count: int
    recording: bool
    busy: bool
    persistent: bool
    inconsistent: bool

    def __post_init__(self) -> None:
        if not isinstance(self.nome, str) or not self.nome:
            raise RegistroMalformadoError(f"bitmap sem nome: {self.nome!r}")
        if self.granularity <= 0 or self.count < 0:
            raise RegistroMalformadoError(
                f"bitmap {self.nome!r}: granularity {self.granularity} e count {self.count}"
            )
        if self.inconsistent and (self.recording or self.busy or not self.persistent):
            raise FonteIncoerenteError(
                f"bitmap {self.nome!r} inconsistent com recording={self.recording}, "
                f"busy={self.busy}, persistent={self.persistent}: o QEMU documenta que "
                f"inconsistent implica persistent, e nem recording nem busy"
            )

    def para_json(self) -> dict[str, Any]:
        return {
            "nome": self.nome,
            "granularity": self.granularity,
            "count": self.count,
            "recording": self.recording,
            "busy": self.busy,
            "persistent": self.persistent,
            "inconsistent": self.inconsistent,
        }

    @classmethod
    def de_json(cls, dados: Mapping[str, Any]) -> "EstadoDoBitmap":
        return cls(
            nome=_exigir_texto(dados, "nome"),
            granularity=_exigir_inteiro(dados, "granularity"),
            count=_exigir_inteiro(dados, "count"),
            recording=_exigir_bool(dados, "recording"),
            busy=_exigir_bool(dados, "busy"),
            persistent=_exigir_bool(dados, "persistent"),
            inconsistent=_exigir_bool(dados, "inconsistent"),
        )


@dataclass(frozen=True)
class ImagemNoInventario:
    """Uma imagem da cadeia de backing de um disco, com os bitmaps que ela tem.

    `arquivo` e a IDENTIDADE da imagem: o `filename` do `query-block`, que a M5 usou
    para casar node-name e disco. Sem ele, dois inventarios do mesmo disco nao
    distinguem "a cadeia mudou de forma" de "os bitmaps se moveram dentro da mesma
    cadeia" — e isso separa resync de reconciliacao (T7). Nao e o node-name: o N
    do `libvirt-N-format` nao seguia a ordem dos targets na leitura da M5, entao
    ele nao carrega a identidade do disco; que ele mude entre reinicios e suposicao,
    nao medida.

    UMA CHAVE SO, para todas as imagens: o `filename` do `ImageInfo` —
    `inserted.image.filename` no topo, e `backing-image.filename` descendo a cadeia.
    NUNCA `inserted.file`: ele existe uma vez por dispositivo e nao popula a cadeia.
    Ler `inserted.file` no topo e `backing-image.filename` no resto seria dar a dois
    conceitos a mesma aparencia, e "unico na cadeia" passaria ou reprovaria pelo
    motivo errado. A saida crua da M5 nao foi guardada: que o fork preenche essa
    chave como o esquema diz e item a conferir na proxima leitura.
    """

    arquivo: str
    bitmaps: tuple[EstadoDoBitmap, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.arquivo, str) or not self.arquivo:
            raise RegistroMalformadoError(f"imagem sem arquivo: {self.arquivo!r}")
        nomes = [b.nome for b in self.bitmaps]
        if len(set(nomes)) != len(nomes):
            raise RegistroMalformadoError(f"imagem com bitmap repetido: {nomes}")

    def para_json(self) -> dict[str, Any]:
        return {"arquivo": self.arquivo, "bitmaps": [b.para_json() for b in self.bitmaps]}

    @classmethod
    def de_json(cls, dados: Mapping[str, Any]) -> "ImagemNoInventario":
        return cls(
            arquivo=_exigir_texto(dados, "arquivo"),
            bitmaps=tuple(
                EstadoDoBitmap.de_json(b) for b in _exigir_lista_de_objetos(dados, "bitmaps")
            ),
        )


@dataclass(frozen=True)
class DiscoNoInventario:
    """Um disco da VM, pelo TARGET (`vda`), e nunca pelo node-name.

    O node-name do QEMU e `libvirt-N-format`, e na leitura da M5 o N nao seguia a
    ordem dos targets (`vda` era `libvirt-1`, o cdrom `sda`, `libvirt-2`). Isso
    basta para nao usa-lo como identidade. SUPOSICAO, e nao medida: que o libvirt o
    reatribua a cada partida do dominio — a M5 viu uma leitura, num boot. Por isso
    o agente le o node-name no momento de agir, casando o `filename` com o caminho
    do volume, e nunca pelo numero.

    PONTO CEGO, dito para quem ler: justificativa de decisao em docstring nao passa
    pelo meta-checador, que so le paragrafo de mecanismo e linha de Riscos. Esta
    afirmava mais do que a M5 mediu ("renumerado a cada partida"), e nada pegou.

    `somente_leitura`: o libvirt nao poe bitmap em disco somente-leitura (M5: o
    cdrom nao recebeu nenhum). A maquina confere com isto a lista de discos que
    recebeu, em vez de confiar no chamador: um disco somente-leitura na lista faria
    o ciclo esperar para sempre por um bitmap impossivel.

    `cadeia`: as imagens de backing, do topo para baixo — as condicoes 1 e 2 do
    ADR-0016 sao sobre ela. Na M5 o volume de dados tinha profundidade zero; isso
    vale para aquela VM, e nao para o parque.

    SUPOSICAO EXPLICITA: a forma de uma cadeia com profundidade maior que zero e
    suposta, e nao medida. A unicidade do `arquivo` e o percurso da cadeia so foram
    exercidos pelos nossos testes, que provam que o codigo faz o que escrevemos, e
    nao que o fork produz essa forma. Se o parque nunca tem profundidade > 0, este
    codigo e peso morto; se tem, a T6 depende de algo nao medido. Quem responde e a
    M2 (censo do parque do cliente).
    """

    disco: str
    somente_leitura: bool
    cadeia: tuple[ImagemNoInventario, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.disco, str) or not self.disco:
            raise RegistroMalformadoError(f"disco invalido: {self.disco!r}")
        if not self.cadeia:
            raise RegistroMalformadoError(f"disco {self.disco!r} sem imagem nenhuma")
        arquivos = [i.arquivo for i in self.cadeia]
        if len(set(arquivos)) != len(arquivos):
            raise RegistroMalformadoError(f"disco {self.disco!r} com imagem repetida: {arquivos}")

    def para_json(self) -> dict[str, Any]:
        return {
            "disco": self.disco,
            "somente_leitura": self.somente_leitura,
            "cadeia": [i.para_json() for i in self.cadeia],
        }

    @classmethod
    def de_json(cls, dados: Mapping[str, Any]) -> "DiscoNoInventario":
        return cls(
            disco=_exigir_texto(dados, "disco"),
            somente_leitura=_exigir_bool(dados, "somente_leitura"),
            cadeia=tuple(
                ImagemNoInventario.de_json(i) for i in _exigir_lista_de_objetos(dados, "cadeia")
            ),
        )


@dataclass(frozen=True)
class ResultadoDeInventario(Resultado):
    """A fotografia que DECIDE se o incremental comeca (ADR-0016).

    A versao anterior trazia `job_em_curso: bool` e nomes soltos — respondia a
    pergunta que era facil de obter, e nao a que decide. Agora traz, por disco e
    por imagem da cadeia, o estado de cada bitmap.

    `jobs_em_curso` FICA, ao lado do `busy`, e cada um diz por que existe: `busy` e
    do BITMAP — alguem o usa, um backup ou uma migracao chegando —; job e do
    DISPOSITIVO, e um backup de terceiro — o nativo da VHI, por exemplo — pode
    rodar sem tocar o nosso bitmap. Sao ids crus, e nao booleano: o id e o que
    separa o zumbi nosso do job de outro sistema, e classifica-lo e da
    reconciliacao (T7). A FORMA DESTE CAMPO NAO FOI MEDIDA: a M5 nao rodou
    `query-block-jobs` no fork, e sob que chave vem o id (`device`, `id`) e
    suposicao. Esta no registro da M5 como item aberto, e a T6 nao depende do campo
    antes de ele ser medido.

    `checkpoints`: os nomes do `checkpoint-list` do libvirt. Bitmap sem checkpoint
    correspondente e a assinatura do ciclo de energia do guest (OpenNebula
    one#6206), e o orfao so aparece cruzando os dois.
    """

    TIPO = "inventario"

    discos: tuple[DiscoNoInventario, ...]
    checkpoints: tuple[str, ...]
    jobs_em_curso: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        nomes = [d.disco for d in self.discos]
        if len(set(nomes)) != len(nomes):
            raise RegistroMalformadoError(f"inventario com disco repetido: {nomes}")
        object.__setattr__(self, "discos", tuple(sorted(self.discos, key=lambda d: d.disco)))

    def _corpo_json(self) -> dict[str, Any]:
        return {
            "discos": [d.para_json() for d in self.discos],
            "checkpoints": list(self.checkpoints),
            "jobs_em_curso": list(self.jobs_em_curso),
        }

    @classmethod
    def _corpo_de_json(cls, dados: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "discos": tuple(
                DiscoNoInventario.de_json(d) for d in _exigir_lista_de_objetos(dados, "discos")
            ),
            "checkpoints": _exigir_lista_de_texto(dados, "checkpoints"),
            "jobs_em_curso": _exigir_lista_de_texto(dados, "jobs_em_curso"),
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


@dataclass(frozen=True)
class ResultadoVmAusente(Resultado):
    """ "A VM nao esta neste no" — desfecho proprio, e nao inventario vazio.

    Pedimos o inventario da VM X no no N, indicado pelo Nova. Entre a indicacao e
    a execucao ela migrou para M. O agente de N responde, N e o no indicado, a
    conferencia de no passa — e um inventario vazio seria verdade sobre N e mentira
    sobre a VM. A reconciliacao leria "nao ha orfao", e o orfao ficaria.

    E a licao do `ler_nome` pela outra porta: la, "nosso mas ilegivel" nao podia
    virar "nao e nosso"; aqui, "a VM nao esta aqui" nao pode virar "nao achei nome
    nosso". Vale para todo efeito de agente, e nao so o inventario: qualquer um
    deles pode chegar a um no de onde a VM ja saiu.
    """

    TIPO = "vm_ausente"


def responde_a(resultado: Resultado, efeito: Efeito) -> bool:
    """Este resultado e deste efeito? Por IGUALDADE, nunca por intersecao.

    Existe para que a funcao certa seja a que esta a mao. Sem ela, quem precisasse
    correlacionar encontraria `se_excluem` pronta — e um resultado de `FecharJanela`
    sobre `vda, vdb` passaria a responder a um `IniciarCopia` sobre `vdb`.

    Tenant, ciclo, tipo, SUJEITO, NO e o conjunto inteiro de chaves. Tenant entra
    porque correlacao que cruzasse tenant seria o oraculo que o ADR-0006 fecha.
    Sujeito, porque as chaves eram proxy da identidade e, sem chave, o proxy e
    vazio. No, porque o agente de outro no nao responde por este — inclusive
    quando o no que respondeu e o indicado, mas a VM ja tinha saido dele: isso e
    `ResultadoVmAusente`, e ele responde, dizendo que ela nao esta la.
    """
    return (
        resultado.tenant_id == efeito.tenant_id
        and resultado.ciclo_id == efeito.ciclo_id
        and resultado.tipo_do_efeito == efeito.TIPO
        and resultado.vm_id == efeito.vm_id
        and resultado.no_que_respondeu == efeito.no
        and set(resultado.chaves) == set(chaves_de(efeito))
    )


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
        raise RegistroMalformadoError(f"sem o campo obrigatorio {nome!r}")
    return dados[nome]


def _exigir_bool(dados: Mapping[str, Any], nome: str) -> bool:
    valor = _exigir(dados, nome)
    if not isinstance(valor, bool):
        raise RegistroMalformadoError(
            f"{nome!r} tem que ser booleano, e veio {valor!r} ({type(valor).__name__}). "
            'Texto nao vira booleano por conveniencia: "false" e verdadeiro.'
        )
    return valor


def _exigir_inteiro(dados: Mapping[str, Any], nome: str) -> int:
    valor = _exigir(dados, nome)
    # `isinstance(True, int)` e verdadeiro em Python, entao booleano precisa ser
    # recusado a mao — senao `True` entra como 1 na telemetria.
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise RegistroMalformadoError(
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
        raise RegistroMalformadoError(f"{nome!r} tem que ser UUID em texto, e veio {valor!r}")
    try:
        return UUID(valor)
    except ValueError as erro:
        raise RegistroMalformadoError(f"{nome!r} nao e UUID: {valor!r}") from erro


def _exigir_chaves(dados: Mapping[str, Any], nome: str) -> tuple[ChaveDeExclusao, ...]:
    """Lista de chaves; vazia vale, repetida nao.

    Mesmo caminho para efeito e resultado — dois leitores de chave seriam dois
    lados, e um deles viraria o frouxo.
    """
    valor = _exigir(dados, nome)
    if isinstance(valor, (str, Mapping)) or not isinstance(valor, (list, tuple)):
        raise RegistroMalformadoError(f"{nome!r} tem que ser lista de chaves, e veio {valor!r}")
    chaves = []
    for item in valor:
        if not isinstance(item, Mapping):
            raise RegistroMalformadoError(f"{nome!r} tem item que nao e objeto: {item!r}")
        chaves.append(ChaveDeExclusao.de_json(item))
    if len(set(chaves)) != len(chaves):
        raise RegistroMalformadoError(f"{nome!r} com chave repetida")
    return tuple(chaves)


def _exigir_texto(dados: Mapping[str, Any], nome: str) -> str:
    valor = _exigir(dados, nome)
    if not isinstance(valor, str):
        raise RegistroMalformadoError(f"{nome!r} tem que ser texto, e veio {valor!r}")
    return valor


def _texto_ou_nada(dados: Mapping[str, Any], nome: str) -> Optional[str]:
    valor = dados.get(nome)
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise RegistroMalformadoError(f"{nome!r} tem que ser texto ou nada, e veio {valor!r}")
    return valor


def _exigir_lista_de_texto(dados: Mapping[str, Any], nome: str) -> tuple[str, ...]:
    valor = _exigir(dados, nome)
    if isinstance(valor, str) or not isinstance(valor, (list, tuple)):
        raise RegistroMalformadoError(f"{nome!r} tem que ser lista de texto, e veio {valor!r}")
    for item in valor:
        if not isinstance(item, str):
            raise RegistroMalformadoError(f"{nome!r} tem item que nao e texto: {item!r}")
    return tuple(valor)


def _exigir_lista_de_objetos(dados: Mapping[str, Any], nome: str) -> tuple[Mapping[str, Any], ...]:
    valor = _exigir(dados, nome)
    if isinstance(valor, (str, Mapping)) or not isinstance(valor, (list, tuple)):
        raise RegistroMalformadoError(f"{nome!r} tem que ser lista de objetos, e veio {valor!r}")
    for item in valor:
        if not isinstance(item, Mapping):
            raise RegistroMalformadoError(f"{nome!r} tem item que nao e objeto: {item!r}")
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
            raise CatalogoAmbiguoError(
                f"TIPO {tipo!r} declarado por duas classes: "
                f"{anterior.__name__} e {classe.__name__}. Uma delas venceria "
                "conforme a ordem de visita, que nao e estavel."
            )
        achados[tipo] = classe
    return achados


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
        raise RegistroMalformadoError(
            f"{classe.TIPO!r} declara alvo {classe.ALVO.value!r}, e o efeito "
            f"chegou com {alvo.value!r}. Contradicao nao se resolve escolhendo um."
        )

    argumentos: dict[str, Any] = {
        "tenant_id": _exigir_uuid(dados, "tenant_id"),
        "ciclo_id": _exigir_uuid(dados, "ciclo_id"),
        "vm_id": _exigir_uuid(dados, "vm_id"),
        "no": _texto_ou_nada(dados, "no"),
    }
    if issubclass(classe, (EfeitoDeDisco, EfeitoDeVm)):
        chaves = _exigir_chaves(dados, "chaves_de_exclusao")
        # As chaves dizem a VM de novo, e as duas expressoes tem que concordar —
        # senao a fila exclui por uma VM e o agente age sobre outra.
        alheias = {c.vm_id for c in chaves} - {argumentos["vm_id"]}
        if alheias:
            raise RegistroMalformadoError(
                f"{classe.TIPO!r} com chaves de VMs diferentes do sujeito: "
                f"{sorted(map(str, alheias))}"
            )
        if issubclass(classe, EfeitoDeDisco):
            if len(chaves) != 1:
                raise RegistroMalformadoError(
                    f"{classe.TIPO!r} age num disco so, e chegou com {len(chaves)} chaves"
                )
            argumentos["disco"] = chaves[0].disco
        else:
            argumentos["discos"] = tuple(c.disco for c in chaves)
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
        "tenant_id": _exigir_uuid(dados, "tenant_id"),
        "ciclo_id": _exigir_uuid(dados, "ciclo_id"),
        "tipo_do_efeito": _exigir_texto(dados, "tipo_do_efeito"),
        "chaves": _exigir_chaves(dados, "chaves"),
        "vm_id": _exigir_uuid(dados, "vm_id"),
        "no_que_respondeu": _texto_ou_nada(dados, "no_que_respondeu"),
    }
    argumentos.update(classe._corpo_de_json(dados))
    return classe(**argumentos)
