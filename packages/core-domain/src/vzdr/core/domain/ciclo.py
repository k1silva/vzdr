"""A maquina do ciclo: as fases, o que cada uma pede, e `avancar`.

A parte DECLARATIVA vem primeiro: quais fases existem, e em que etapas cada uma
pede quais efeitos. As transicoes sao escritas sobre essa tabela — os efeitos que
`avancar` pede saem dela, e nao de uma segunda lista.

A tabela existe antes das transicoes porque e ela que responde uma pergunta que a
varredura do envelope nunca fez: o CONJUNTO de efeitos executa o ciclo inteiro?
A varredura perguntava coisas sobre cada efeito. Duas lacunas passaram por ela —
primeiro faltou o sujeito em dois efeitos, depois faltaram tres efeitos no
conjunto (o ponto de recuperacao, a retirada do export, a remocao dos checkpoints
anteriores) — e a segunda so apareceu quando alguem enumerou as fases a mao. O
teste de cobertura fase <-> efeito faz a proxima aparecer no build.

NOMES. Cada fase e nomeada por QUEM ELA ESPERA, que e o criterio do `Alvo` subindo
um nivel: dois esperados que falham separado sao duas fases. Foi o que dividiu a
primeira conferencia em LOCALIZANDO (espera o Nova) e VALIDANDO (espera o agente).

A excecao declarada e LIBERANDO, que espera a receptora e o agente juntos. Ela nao
se divide porque e a unica fase em que falhar nao pode falhar o ciclo: quando ela
comeca, o ponto de recuperacao ja existe. Falha nela e "concluido com residuo", e
o residuo vai para a reconciliacao — atraso nela nao atrasa protecao nenhuma,
entao "quem se espera" nao muda o que o operador precisa saber.

DESFECHO. Nao ha enum de desfecho neste modulo, e isto e a decisao, e nao uma
lacuna: o desfecho de um ciclo terminado E `saude.Desfecho`. Um tipo proprio aqui
seria o mesmo conceito nascendo duas vezes — o erro que a `degradada` ja custou
uma vez entre a dr-006 e a dr-001 —, e uma tabela de traducao entre os dois
precisaria de teste para nao divergir. Sem tipo proprio, nao ha onde escrever um
desfecho sem par: desfecho novo nasce em saude.py, ou nao nasce. E o movimento
do `RemoverCheckpointsAnteriores`: em vez de recusar o valor ilegal, remover o
lugar onde escreve-lo.

O RELOGIO ENTRA POR PARAMETRO, como em saude.py. O estado carrega dois instantes,
`iniciado_em` e `fase_desde`; o terceiro relogio da conversa, o ponto mais
recente, e da VM e nao do ciclo — atravessa ciclos, e um ciclo que nunca iniciou
tem que deixa-lo envelhecer —, entao mora com quem calcula a idade.

Este modulo roda no hypervisor (fecho de 3.9, ADR-0007): sem sintaxe 3.10+.
"""

import enum
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from vzdr.core.domain.efeitos import (
    Alvo,
    CercarDestino,
    ConfirmarNoDestino,
    ConsultarNoDaVm,
    DescartarBitmap,
    Efeito,
    EfeitoDeDisco,
    EfeitoDeVm,
    FecharJanela,
    IniciarCopia,
    InventariarVm,
    PublicarExport,
    RegistrarPontoDeRecuperacao,
    RemoverCheckpointsAnteriores,
    Resultado,
    ResultadoDeCopia,
    ResultadoDeInventario,
    ResultadoDeLocalizacao,
    ResultadoSimples,
    ResultadoVmAusente,
    RetirarExport,
    responde_a,
)
from vzdr.core.domain.saude import Desfecho

__all__ = [
    "EFEITOS_DA_FASE",
    "ETAPAS_DA_FASE",
    "RESULTADO_ESPERADO",
    "EstadoDoCiclo",
    "Fase",
    "MigracaoSemResyncError",
    "Transicao",
    "TransicaoInvalidaError",
    "abandonar",
    "abandono_deixa_residuo",
    "avancar",
    "iniciar",
    "no_do_proximo_ciclo",
]


class Fase(enum.Enum):
    """As fases nao terminais. Caminho normal, e a de cercamento."""

    LOCALIZANDO = "localizando"
    VALIDANDO = "validando"
    FECHANDO_JANELA = "fechando_janela"
    PUBLICANDO = "publicando"
    COPIANDO = "copiando"
    CONFIRMANDO = "confirmando"
    REGISTRANDO_PONTO = "registrando_ponto"
    LIBERANDO = "liberando"
    #: Da reconciliacao: a evidencia nao chegou, e o destino e cercado. As
    #: transicoes que a alcancam sao da T7; ela esta declarada aqui porque o
    #: `CercarDestino` tem que ser emitido por alguma fase, senao e efeito morto.
    CERCANDO = "cercando"


#: Cada fase e uma SEQUENCIA de etapas; a etapa seguinte so e pedida quando todos
#: os efeitos da anterior responderam. Dentro de uma etapa, nada se exclui — e ha
#: teste disso sobre a tabela inteira, porque e o que torna seguro pedir a etapa
#: toda de uma vez.
ETAPAS_DA_FASE: dict[Fase, tuple[tuple[type[Efeito], ...], ...]] = {
    # Leituras. O abandono destas nao deixa residuo nenhum, e e por isso que a
    # validade do bitmap e decidida antes de qualquer trabalho caro.
    Fase.LOCALIZANDO: ((ConsultarNoDaVm,),),
    Fase.VALIDANDO: ((InventariarVm,),),
    # Daqui em diante, abandonar deixa residuo — a comecar pelo checkpoint.
    Fase.FECHANDO_JANELA: ((FecharJanela,),),
    Fase.PUBLICANDO: ((PublicarExport,),),
    Fase.COPIANDO: ((IniciarCopia,),),
    Fase.CONFIRMANDO: ((ConfirmarNoDestino,),),
    Fase.REGISTRANDO_PONTO: ((RegistrarPontoDeRecuperacao,),),
    # A unica fase cujos efeitos se excluem ENTRE SI: o de VM segura todas as
    # chaves, e os dois de disco seguram a mesma quando sao do mesmo disco. Por
    # isso tres etapas, e nao uma. A ordem:
    # - o export sai primeiro: corta o caminho de escrita do destino antes de mexer
    #   no estado da origem, e e o que torna verdadeira a frase "export fechado
    #   entre ciclos";
    # - o bitmap temporario, disco a disco — os discos nao se excluem entre si;
    # - os checkpoints anteriores por ultimo, porque o efeito e de VM e segura
    #   todas as chaves: pedi-lo antes faria os de disco esperarem por ele.
    Fase.LIBERANDO: (
        (RetirarExport,),
        (DescartarBitmap,),
        (RemoverCheckpointsAnteriores,),
    ),
    Fase.CERCANDO: ((CercarDestino,),),
}

#: O que cada fase pede, sem a ordem. Derivada das etapas, e nao escrita de novo.
EFEITOS_DA_FASE: dict[Fase, tuple[type[Efeito], ...]] = {
    fase: tuple(classe for etapa in etapas for classe in etapa)
    for fase, etapas in ETAPAS_DA_FASE.items()
}


def abandono_deixa_residuo(fase: Fase) -> bool:
    """Abandonar esta fase deixa algo para limpar?

    Derivado dos efeitos, e nao enumerado: uma fase deixa residuo se algum efeito
    dela segura chave — isto e, toca disco. Leitura nao segura chave, entao
    abandona-la so custa tempo.

    Importa para o desfecho de um prazo estourado: onde ha residuo — o checkpoint
    criado, o export publicado —, trabalho foi tentado, e chamar isso de "nunca
    iniciou" o tiraria da taxa de falha, deixando-a otimista, que e a direcao
    perigosa.

    LIMITE: responde sobre a FASE, e nao sobre o CICLO. A T6 precisa saber se o
    ciclo ja deixou residuo, e isso e propriedade do caminho: um ciclo que volta a
    LOCALIZANDO depois de FECHANDO_JANELA — a VM migrou no meio, e a T7 vai querer
    localiza-la de novo — esta numa fase sem residuo com um checkpoint ja criado.
    Um prazo ali, decidido por esta funcao, daria "nunca iniciou". Por isso o
    desfecho do prazo NAO sai daqui: sai de um fato do estado que so vira
    verdadeiro e nunca volta (T5). Esta funcao e o que alimenta esse fato a cada
    fase em que o ciclo entra, e nao a resposta.

    O mesmo limite aparece no CERCANDO, onde a resposta e certa pelo motivo
    errado. A preempcao segura chave para DESTRUIR, e nao deixa residuo novo; a
    resposta certa ali vem de o ciclo ja ter escrito antes de chegar — que e o
    argumento do caminho. A derivacao fica como esta de proposito: mudada, faria o
    CERCANDO responder "sem residuo", e um prazo la poderia dar "nunca iniciou",
    que seria pior.
    """
    return any(issubclass(e, (EfeitoDeDisco, EfeitoDeVm)) for e in EFEITOS_DA_FASE[fase])


# ── A maquina ───────────────────────────────────────────────────────────────

#: O caminho normal, na ordem da enumeracao. CERCANDO fica fora: e da
#: reconciliacao (T7).
_CAMINHO_NORMAL = tuple(f for f in Fase if f is not Fase.CERCANDO)

#: Que tipo de resultado responde a cada efeito. Sobre o catalogo inteiro — ha
#: teste —, para que efeito novo nao herde em silencio um tipo de resultado
#: errado. `ResultadoVmAusente` responde a qualquer efeito de agente, e nao entra
#: aqui: e a VM dizendo que nao esta, e nao uma resposta ao que se pediu.
RESULTADO_ESPERADO: dict[type[Efeito], type[Resultado]] = {
    ConsultarNoDaVm: ResultadoDeLocalizacao,
    InventariarVm: ResultadoDeInventario,
    FecharJanela: ResultadoSimples,
    PublicarExport: ResultadoSimples,
    IniciarCopia: ResultadoDeCopia,
    ConfirmarNoDestino: ResultadoSimples,
    RegistrarPontoDeRecuperacao: ResultadoSimples,
    RetirarExport: ResultadoSimples,
    DescartarBitmap: ResultadoSimples,
    RemoverCheckpointsAnteriores: ResultadoSimples,
    CercarDestino: ResultadoSimples,
}


class MigracaoSemResyncError(RuntimeError):
    """O proximo ciclo nao tem no de origem certo, e por isso nao comeca.

    Depois de uma migracao detectada, os dois nos candidatos estao errados. O
    gravado (A) faz o proximo ciclo detectar a migracao de novo, e de novo: a VM
    para de ser protegida com 0% de falha no painel, porque `NUNCA_INICIOU` fica
    fora da taxa. O encontrado (B) e pior: o proximo ciclo nao detecta nada e
    copia com o bitmap que atravessou o evento de host — o espelho errado em
    silencio que a decisao 1 do ADR-0012 existe para impedir.

    O no certo so existe depois de o bitmap ser descartado e a VM ressincronizada,
    e esse caminho nao esta construido (ADR-0012, M4). Ate la, o agendador que
    pede o no recebe isto, e nao um laco silencioso.
    """


class TransicaoInvalidaError(ValueError):
    """Um resultado responde a um efeito pendente, e nao e o tipo que o responde.

    Nao e "resultado de outro ciclo" nem "resultado repetido": esses sao
    descartados em silencio, porque acontecem por construcao (fila com retry,
    resposta atrasada). Isto e contrato quebrado entre quem pediu e quem respondeu,
    e engolir seria aceitar um estado que ninguem descreveu.
    """


def _exigir_fuso(nome: str, instante: Optional[datetime]) -> None:
    if instante is not None and instante.tzinfo is None:
        raise ValueError(
            f"{nome} sem fuso: {instante!r}. Todo instante do dominio tem fuso (saude.py)"
        )


@dataclass(frozen=True)
class EstadoDoCiclo:
    """Tudo o que a maquina sabe de um ciclo, e nada que ela possa recalcular.

    Imutavel: `avancar` devolve um estado novo, e o antigo continua valendo para
    quem o tinha — e o que torna um cenario de falha uma lista de entradas.
    """

    tenant_id: UUID
    ciclo_id: UUID
    vm_id: UUID
    discos: tuple[str, ...]
    #: O no gravado no ciclo anterior (ADR-0012). Comparado com o que o Nova
    #: responde, e e a primeira coisa que o ciclo faz.
    no_de_origem: str
    iniciado_em: datetime
    fase: Fase
    #: Quando o ciclo ENTROU na fase corrente. So muda ao entrar numa fase: o
    #: tempo passar nao comeca fase nenhuma. E a base do prazo da fase (T6).
    fase_desde: datetime
    #: Indice em `ETAPAS_DA_FASE[fase]`.
    etapa: int
    #: Os efeitos pedidos que ainda nao responderam.
    pendentes: tuple[Efeito, ...]
    #: So vira verdadeiro, e nunca volta. Fato do CAMINHO, e nao da fase: um ciclo
    #: que reentra numa leitura depois de escrever continua com residuo. E dele, e
    #: nao da fase corrente, que sai o desfecho de um abandono.
    ja_deixou_residuo: bool
    #: Onde o Nova disse que a VM esta, quando ja disse. E a PROCEDENCIA do no
    #: dos efeitos de agente (ADR-0015, emenda de 2026-09-30), e nao o gravado:
    #: sem migracao os dois sao iguais quando o efeito sai, mas sao duas expressoes
    #: do mesmo fato, e o envelope diz qual e a dele.
    no_encontrado: Optional[str]
    #: Os nomes que o inventario achou, crus, quando ja respondeu. A T5 so decide
    #: por `job_em_curso`; classificar os nomes (`ler_nome`, tres estados) e
    #: achar orfaos e da T7. Guardados aqui porque o ciclo que os viu e o lugar
    #: mais barato de registra-los — descartados, a evidencia morreria em
    #: `avancar` e a T7 teria que perguntar de novo.
    nomes_no_inventario: Optional[tuple[str, ...]]
    #: Quando o ponto de recuperacao deste ciclo foi registrado, se foi.
    ponto_registrado_em: Optional[datetime]
    #: `None` enquanto o ciclo corre. Terminado, e o `Desfecho` de saude.py — nao
    #: ha outro tipo de desfecho (ver o topo do modulo).
    desfecho: Optional[Desfecho]

    def __post_init__(self) -> None:
        _exigir_fuso("iniciado_em", self.iniciado_em)
        _exigir_fuso("fase_desde", self.fase_desde)
        _exigir_fuso("ponto_registrado_em", self.ponto_registrado_em)
        if not self.discos or len(set(self.discos)) != len(self.discos):
            raise ValueError(f"discos vazios ou repetidos: {self.discos}")
        object.__setattr__(self, "discos", tuple(sorted(self.discos)))

    @property
    def migracao_detectada(self) -> bool:
        """O Nova disse que a VM esta num no diferente do gravado (ADR-0012)."""
        return self.no_encontrado is not None and self.no_encontrado != self.no_de_origem


@dataclass(frozen=True)
class Transicao:
    """O estado novo e os efeitos a pedir. UM tipo de retorno para toda entrada.

    "Nada aconteceu" — entrada `None`, resultado de outro ciclo, resultado
    repetido — e uma Transicao com o mesmo estado e zero efeitos. "Terminou" e
    `estado.desfecho`, um campo, e NUNCA se deduz de zero efeitos: um ciclo que
    espera tambem nao pede nada, e um que termina pode pedir limpeza (T6). O
    chamador nao distingue dois tipos de retorno, e nao confunde os dois casos.
    """

    estado: EstadoDoCiclo
    efeitos: tuple[Efeito, ...]

    @property
    def terminou(self) -> bool:
        return self.estado.desfecho is not None


def _no_do_agente(estado: EstadoDoCiclo) -> str:
    """O no de um efeito de agente: o que o Nova disse. Antes de ele dizer, nao ha
    efeito de agente — a comparacao do no e a primeira coisa (ADR-0012)."""
    if estado.no_encontrado is None:
        raise TransicaoInvalidaError("efeito de agente pedido antes de o Nova dizer onde a VM esta")
    return estado.no_encontrado


def _pedir(estado: EstadoDoCiclo, fase: Fase, etapa: int) -> tuple[Efeito, ...]:
    """Os efeitos de uma etapa, construidos da tabela — a unica lista que existe."""
    pedidos: list[Efeito] = []
    for classe in ETAPAS_DA_FASE[fase][etapa]:
        base: dict[str, Any] = {
            "tenant_id": estado.tenant_id,
            "ciclo_id": estado.ciclo_id,
            "vm_id": estado.vm_id,
            "no": _no_do_agente(estado) if classe.ALVO is Alvo.AGENTE_DE_ORIGEM else None,
        }
        if issubclass(classe, EfeitoDeVm):
            pedidos.append(classe(**base, discos=estado.discos))
        elif issubclass(classe, EfeitoDeDisco):
            pedidos += [classe(**base, disco=d) for d in estado.discos]
        else:
            pedidos.append(classe(**base))
    return tuple(pedidos)


def _entrar(estado: EstadoDoCiclo, fase: Fase, agora: datetime) -> Transicao:
    efeitos = _pedir(estado, fase, 0)
    novo = replace(
        estado,
        fase=fase,
        fase_desde=agora,
        etapa=0,
        pendentes=efeitos,
        ja_deixou_residuo=estado.ja_deixou_residuo or abandono_deixa_residuo(fase),
    )
    return Transicao(novo, efeitos)


def iniciar(
    tenant_id: UUID,
    ciclo_id: UUID,
    vm_id: UUID,
    discos: tuple[str, ...],
    no_de_origem: str,
    agora: datetime,
) -> Transicao:
    """O ciclo comeca perguntando ao Nova onde a VM esta. Nada antes disso."""
    _exigir_fuso("agora", agora)
    vazio = EstadoDoCiclo(
        tenant_id=tenant_id,
        ciclo_id=ciclo_id,
        vm_id=vm_id,
        discos=discos,
        no_de_origem=no_de_origem,
        iniciado_em=agora,
        fase=_CAMINHO_NORMAL[0],
        fase_desde=agora,
        etapa=0,
        pendentes=(),
        ja_deixou_residuo=False,
        no_encontrado=None,
        nomes_no_inventario=None,
        ponto_registrado_em=None,
        desfecho=None,
    )
    return _entrar(vazio, _CAMINHO_NORMAL[0], agora)


def abandonar(estado: EstadoDoCiclo, agora: datetime) -> Transicao:
    """Termina o ciclo sem completa-lo. O desfecho sai dos FATOS do estado.

    - ponto ja registrado: `CONCLUIDO` — a protecao existe, e o que sobrou e
      residuo para a reconciliacao recolher (T7). Reportar falha esconderia um
      ponto que existe;
    - residuo, sem ponto: `FALHOU` — trabalho foi tentado;
    - nem um nem outro: `NUNCA_INICIOU`.

    Nenhum dos tres olha a fase corrente. E isso que deixa a T7 reentrar em
    LOCALIZANDO depois de escrever sem que um prazo ali vire "nunca iniciou".

    `agora` ainda nao e usado, e esta na assinatura porque a T6 o usa: e aqui que
    entram os efeitos de limpeza do abandono, e a telemetria (T8) registra o fim.

    O ciclo seguinte comeca com `no_do_proximo_ciclo(estado)`, e nunca com o
    `no_de_origem` carregado adiante: depois de migracao, isso prende a VM num
    laco silencioso de `NUNCA_INICIOU` (ver `MigracaoSemResyncError`).
    """
    _exigir_fuso("agora", agora)
    if estado.desfecho is not None:
        return Transicao(estado, ())
    if estado.ponto_registrado_em is not None:
        desfecho = Desfecho.CONCLUIDO
    elif estado.ja_deixou_residuo:
        desfecho = Desfecho.FALHOU
    else:
        desfecho = Desfecho.NUNCA_INICIOU
    return Transicao(replace(estado, pendentes=(), desfecho=desfecho), ())


def no_do_proximo_ciclo(estado: EstadoDoCiclo) -> str:
    """O no que o proximo ciclo desta VM grava como `no_de_origem`.

    E o uso correto da maquina escrito como funcao, porque o uso obvio — carregar
    o `no_de_origem` adiante — e silencioso e otimista depois de uma migracao.

    - sem migracao: o no onde o ciclo encontrou a VM, ou o gravado, se o Nova nao
      chegou a responder;
    - com migracao: `MigracaoSemResyncError`. Nenhum dos dois nos e certo antes do
      resync, e o resync nao existe ainda (M4).
    """
    if estado.desfecho is None:
        raise ValueError("o ciclo ainda corre; o no do proximo sai de um ciclo terminado")
    if estado.migracao_detectada:
        raise MigracaoSemResyncError(
            f"VM {estado.vm_id} migrou de {estado.no_de_origem} para "
            f"{estado.no_encontrado}: o bitmap tem que ser descartado e a VM "
            f"ressincronizada antes do proximo ciclo (ADR-0012)"
        )
    return estado.no_encontrado or estado.no_de_origem


def _deu_certo(resultado: Resultado) -> bool:
    if isinstance(resultado, ResultadoSimples):
        return resultado.sucesso
    if isinstance(resultado, ResultadoDeCopia):
        # Resultado e a resposta final a um efeito, e nao relatorio de progresso:
        # copia que responde sem ter concluido nao concluiu.
        return resultado.concluido
    if isinstance(resultado, ResultadoDeInventario):
        # Job em curso de outro ciclo: este nao comeca por cima dele. Decidir o
        # que fazer com o job e da reconciliacao (T7) — e, ate ela existir, uma
        # copia que falhou deixando o job no ar faz todo ciclo seguinte terminar
        # aqui, fora da taxa de falha. Esta na tabela de Riscos do plano.
        return not resultado.job_em_curso
    return True


def avancar(estado: EstadoDoCiclo, entrada: Optional[Resultado], agora: datetime) -> Transicao:
    """Um passo da maquina. Pura: mesma entrada, mesmo `agora`, mesma saida.

    `entrada` `None` e o agendador deixando o tempo correr. Hoje nao muda nada; a
    T6 e quem decide prazo a partir de `agora - fase_desde`.
    """
    _exigir_fuso("agora", agora)
    nada = Transicao(estado, ())
    # Ciclo terminado descarta tudo: resultado atrasado de um ciclo que ja acabou
    # nao reabre nada.
    if estado.desfecho is not None or entrada is None:
        return nada
    if estado.fase not in _CAMINHO_NORMAL:
        raise TransicaoInvalidaError(
            f"{estado.fase.value}: as transicoes desta fase sao da reconciliacao (T7)"
        )
    respondido = next((e for e in estado.pendentes if responde_a(entrada, e)), None)
    if respondido is None:
        # De outro ciclo, de outra VM, de outro no, ou repetido: descartado.
        return nada
    if isinstance(entrada, ResultadoVmAusente):
        return abandonar(estado, agora)
    esperado = RESULTADO_ESPERADO[type(respondido)]
    if not isinstance(entrada, esperado):
        raise TransicaoInvalidaError(
            f"{respondido.TIPO} e respondido por {esperado.__name__}, "
            f"e chegou {type(entrada).__name__}"
        )
    if isinstance(entrada, ResultadoDeLocalizacao):
        estado = replace(estado, no_encontrado=entrada.no_atual)
        # A comparacao do no, antes de qualquer outra coisa (ADR-0012): bitmap que
        # atravessou evento de host nao e usado. O ciclo nao executa; o que vem
        # depois — descartar o bitmap e ressincronizar — nao esta construido (M4),
        # e `no_do_proximo_ciclo` recusa em vez de deixar o proximo ciclo errar.
        if estado.migracao_detectada:
            return abandonar(estado, agora)
    if isinstance(entrada, ResultadoDeInventario):
        estado = replace(estado, nomes_no_inventario=entrada.nomes_encontrados)
    if not _deu_certo(entrada):
        return abandonar(estado, agora)
    if isinstance(respondido, RegistrarPontoDeRecuperacao):
        estado = replace(estado, ponto_registrado_em=agora)
    # Por VALOR, e nao por identidade: o efeito e dataclass congelada com
    # igualdade por valor, e `_pedir` nunca gera dois iguais. Identidade so
    # funciona enquanto ninguem reconstruir a tupla — e no dia em que alguem a
    # canonizar, o respondido nunca sairia, e o ciclo esperaria para sempre uma
    # resposta que ja chegou.
    pendentes = tuple(e for e in estado.pendentes if e != respondido)
    estado = replace(estado, pendentes=pendentes)
    if pendentes:
        return Transicao(estado, ())
    proxima_etapa = estado.etapa + 1
    if proxima_etapa < len(ETAPAS_DA_FASE[estado.fase]):
        efeitos = _pedir(estado, estado.fase, proxima_etapa)
        return Transicao(replace(estado, etapa=proxima_etapa, pendentes=efeitos), efeitos)
    posicao = _CAMINHO_NORMAL.index(estado.fase)
    if posicao + 1 < len(_CAMINHO_NORMAL):
        return _entrar(estado, _CAMINHO_NORMAL[posicao + 1], agora)
    return Transicao(replace(estado, desfecho=Desfecho.CONCLUIDO), ())
