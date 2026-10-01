"""As fases do ciclo, e o que cada uma pede.

Esta e a parte DECLARATIVA da maquina: quais fases existem, e qual efeito cada
uma emite. As transicoes — `avancar(estado, entrada, agora)` — sao da T5, e sao
escritas sobre esta tabela.

Ela existe antes da T5 porque e a tabela que responde uma pergunta que a
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

Os desfechos terminais nao estao aqui. Eles sao da T5, e tem que se reconciliar
com `Desfecho` de saude.py — o mesmo conceito nao pode nascer duas vezes.

Este modulo roda no hypervisor (fecho de 3.9, ADR-0007): sem sintaxe 3.10+.
"""

import enum

from vzdr.core.domain.efeitos import (
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
    RetirarExport,
)

__all__ = ["EFEITOS_DA_FASE", "Fase", "abandono_deixa_residuo"]


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


EFEITOS_DA_FASE: dict[Fase, tuple[type[Efeito], ...]] = {
    # Leituras. O abandono destas nao deixa residuo nenhum, e e por isso que a
    # validade do bitmap e decidida antes de qualquer trabalho caro.
    Fase.LOCALIZANDO: (ConsultarNoDaVm,),
    Fase.VALIDANDO: (InventariarVm,),
    # Daqui em diante, abandonar deixa residuo — a comecar pelo checkpoint.
    Fase.FECHANDO_JANELA: (FecharJanela,),
    Fase.PUBLICANDO: (PublicarExport,),
    Fase.COPIANDO: (IniciarCopia,),
    Fase.CONFIRMANDO: (ConfirmarNoDestino,),
    Fase.REGISTRANDO_PONTO: (RegistrarPontoDeRecuperacao,),
    Fase.LIBERANDO: (RetirarExport, DescartarBitmap, RemoverCheckpointsAnteriores),
    Fase.CERCANDO: (CercarDestino,),
}


def abandono_deixa_residuo(fase: Fase) -> bool:
    """Abandonar esta fase deixa algo para limpar?

    Derivado dos efeitos, e nao enumerado: uma fase deixa residuo se algum efeito
    dela segura chave — isto e, toca disco. Leitura nao segura chave, entao
    abandona-la so custa tempo.

    E a linha que a T6 usa para decidir o desfecho de um prazo estourado: so fase
    SEM residuo pode terminar em "nunca iniciou". Onde ha residuo — o checkpoint
    criado, o export publicado —, trabalho foi tentado, e tirar isso da taxa de
    falha a deixaria otimista, que e a direcao perigosa.
    """
    return any(issubclass(e, (EfeitoDeDisco, EfeitoDeVm)) for e in EFEITOS_DA_FASE[fase])
