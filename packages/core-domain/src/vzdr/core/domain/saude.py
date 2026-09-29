"""Saude da protecao: se esta degradada, e quanto falha.

Tudo aqui e CONTA sobre fatos, nunca marca guardada. `degradada` e funcao de
(idade do ponto de recuperacao mais recente, RPO do tier), calculada na hora de
responder. Marca diverge do fato, e ai a tela mente sobre protecao — que num
produto de DR e a unica coisa que ela nao pode fazer.

TRES REGRAS DE FORMA, e cada uma existe porque a versao natural e a errada:

- **O relogio entra por parametro.** Nenhuma funcao deste modulo le a hora. Funcao
  que le o relogio por dentro nao e reproduzivel, o teste nao consegue fixar o
  instante, e a falha e silenciosa: passa hoje e reprova em outro segundo, em
  outro fuso, na virada do horario de verao. Ha teste que verifica isso lendo o
  codigo, e nao so combinando.

- **O fator e parametro com padrao, nao constante.** Depende de perfil de parque,
  e a spec proibe constante derivada de parque. O padrao de 2x o RPO vem da spec:
  um ciclo perdido e ruido, dois e padrao.

- **`degradada` nao vira coluna depois.** Vai chegar o dia de "liste todas as VMs
  degradadas" numa consulta, e a saida obvia vai parecer materializar a coluna
  por desempenho. A resposta e view ou expressao computada no SQL — esta mesma
  conta, escrita uma vez mais, na linguagem de la. Campo que nasce de pressao de
  desempenho nao volta atras, e a partir dele existem duas fontes de verdade que
  podem discordar. E o mesmo raciocinio que recusou a coluna `origem` na
  auditoria.

E `degradada` nao e desprotegida: os pontos existentes continuam validos. O que
para e a criacao de pontos novos no ritmo prometido.

Este modulo roda no hypervisor (fecho de 3.9, ADR-0007): sem sintaxe 3.10+.
"""

import enum
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Optional

__all__ = [
    "FATOR_PADRAO",
    "Desfecho",
    "esta_degradada",
    "idade_do_ponto",
    "taxa_de_falha",
]

#: Degradada quando o ponto passa de 2x o RPO do tier. Um ciclo perdido e ruido;
#: dois e padrao. E por TEMPO, nao por tentativas: tres falhas num tier de 1 hora
#: e tres num de 24 horas sao situacoes diferentes, e contar tentativas trataria
#: as duas igual.
FATOR_PADRAO = 2.0


class Desfecho(enum.Enum):
    """Como um ciclo terminou, no que importa para a taxa de falha.

    `NUNCA_INICIOU` e achado de reconciliacao, nao falha de copia, e por isso nao
    e `FALHOU`. Sem a distincao, ciclo que nao aconteceu entra na taxa de falha
    junto com ciclo que deu errado, e os numeros de confiabilidade mentem
    justamente na metrica que vai dimensionar o produto.

    O registro completo — motivo, bytes, duracao por fase — e da telemetria, na
    T8. Isto e so o recorte que a conta precisa.
    """

    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    NUNCA_INICIOU = "nunca_iniciou"


def idade_do_ponto(ultimo_ponto: Optional[datetime], agora: datetime) -> Optional[timedelta]:
    """Quanto tempo desde o ponto de recuperacao mais recente.

    `agora` e argumento, e nao `datetime.now()`: ver o topo do modulo.

    `None` quando ainda nao existe ponto nenhum, e isso NAO e idade zero nem
    idade infinita. VM sem ponto ainda nao esta protegida — e outra coisa que
    `degradada`, que pressupoe pontos validos. Colapsar os dois estados faria a
    tela dizer "degradada" de uma VM que nunca foi protegida, ou "em dia" de uma
    que ainda esta no seed. Quem chama decide o que mostrar; esta funcao nao
    escolhe por ele.

    **Todo instante que cruza esta fronteira tem fuso.** Misturar com e sem fuso
    levanta `TypeError` no proprio Python, e e o comportamento certo: subtrair
    hora local de UTC daria uma idade errada por horas. O caso silencioso so
    existe se alguem "consertar" tirando o fuso de um dos lados, e ha teste para
    isso.

    A regra morde de verdade onde a data ENTRA no sistema, e nao aqui: quando o
    `core-003` ler data de JSON, o conversor tem que EXIGIR o deslocamento, e
    recusar texto sem fuso — a mesma regra do `_exigir_bool` em efeitos.py. Texto
    sem fuso aceito la vira instante sem fuso aqui, e ai so falta um lado ter.
    """
    if ultimo_ponto is None:
        return None
    return agora - ultimo_ponto


def esta_degradada(
    idade: timedelta,
    rpo: timedelta,
    fator: float = FATOR_PADRAO,
) -> bool:
    """Degradada quando o ponto passa de `fator` vezes o RPO.

    Recebe a idade ja calculada. E o que torna a funcao livre de relogio: quem
    chama fez a subtracao, com o `agora` que escolheu.

    O parametro se chama `idade`, e nao `idade_do_ponto`, porque o segundo nome
    e o da funcao deste modulo: a sombra a tornaria inalcancavel aqui dentro, e
    quem tentasse chama-la receberia "'timedelta' object is not callable" — que
    nao sugere a causa.

    Estritamente maior: no limite exato ainda nao degradou. A diferenca e de um
    instante, e importa so para o teste ser preciso sobre onde a fronteira mora.
    """
    if rpo <= timedelta(0):
        raise ValueError(f"RPO tem que ser positivo, e veio {rpo}")
    if fator <= 0:
        raise ValueError(f"fator tem que ser positivo, e veio {fator}")
    return idade > rpo * fator


def taxa_de_falha(desfechos: Iterable[Desfecho]) -> Optional[float]:
    """Falhas sobre tentativas, sem contar o que nao aconteceu.

    `NUNCA_INICIOU` fica fora do numerador E do denominador. Fora so do
    numerador, ele diluiria a taxa, e ciclo que nao aconteceu faria a
    confiabilidade parecer melhor do que e.

    `None` quando nao houve tentativa nenhuma, e nao `0.0`. Zero sobre zero como
    zero diria "confiabilidade perfeita" sem evidencia nenhuma — e um parque
    inteiro que so teve `NUNCA_INICIOU` e exatamente o caso em que isso seria
    mais falso.

    **O agregado correto e concatenar**, nunca tirar media. Para a taxa de um
    parque, passe os desfechos de todas as VMs numa chamada so. Media das taxas
    por VM esta errada de dois jeitos: pesa igual uma VM com duas tentativas e uma
    com duzentas, e `None` nao tem media — descarta-lo em silencio e voltar a
    confiabilidade perfeita sem evidencia, por outra porta.

    Repare no que isto NAO diz sobre `degradada`: `NUNCA_INICIOU` entra na idade
    do ponto, porque ciclo que nao aconteceu nao produziu ponto e a idade continua
    crescendo. Nao entra aqui. As duas coisas medem coisas diferentes, e e
    exatamente por isso que o mesmo desfecho conta numa e nao na outra.
    """
    tentativas = 0
    falhas = 0
    for desfecho in desfechos:
        if desfecho is Desfecho.NUNCA_INICIOU:
            continue
        tentativas += 1
        if desfecho is Desfecho.FALHOU:
            falhas += 1
    if tentativas == 0:
        return None
    return falhas / tentativas
