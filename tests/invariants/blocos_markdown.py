"""Leitura de markdown comum aos checadores.

Existe para que dois checadores nao tenham dois removedores de bloco de codigo.
Onde dois caminhos fazem o mesmo trabalho, o defeito mora no lado mais solto —
e um removedor que aprende a grafia `~~~` enquanto o outro nao aprende e
exatamente isso. Ver AGENTS.md.
"""

import re

__all__ = ["linhas_fora_de_blocos", "sem_blocos_de_codigo"]

#: Cerca, pelo CommonMark: crase ou til, tres ou mais, com ate tres espacos de
#: indentacao. As tres variacoes importam e nenhuma e exotica — `~~~` e o que se
#: escolhe quando o conteudo tem crase, e quatro crases e o jeito normal de citar
#: um bloco que ja contem tres. O template tem as duas coisas.
_CERCA = re.compile(r"^(?P<ind>[ ]{0,3})(?P<marca>`{3,}|~{3,})(?P<resto>.*)$")


def linhas_fora_de_blocos(texto: str) -> list[tuple[int, str]]:
    """(numero, linha) de cada linha fora de bloco de codigo cercado.

    Devolve NUMEROS, e nao so texto, por causa de um defeito que quase entrou: o
    checador de definicao unica decidia o que estava fora de bloco comparando o
    TEXTO da linha com um conjunto. Uma definicao citada dentro de uma cerca, com
    o mesmo texto da definicao de verdade, passava por visivel e contava duas
    vezes — falso positivo justamente no caso "citei a definicao". Posicao e
    identidade de linha; texto nao e.

    Varredor em vez de uma expressao regular so porque o fechamento depende da
    abertura — mesmo caractere, e pelo menos o mesmo tanto. Retrovisor com
    "pelo menos N" nao e expressavel em `re`, e a alternativa seria casar `{3}`
    fixo e deixar as outras grafias vazarem, que e cobrir metade.
    """
    fora: list[tuple[int, str]] = []
    pendente: list[tuple[int, str]] = []
    aberta: tuple[str, int] | None = None

    for numero, linha in enumerate(texto.splitlines(), 1):
        casou = _CERCA.match(linha)
        if aberta is None:
            if casou is not None:
                marca = casou.group("marca")
                aberta = (marca[0], len(marca))
                pendente = [(numero, linha)]
            else:
                fora.append((numero, linha))
            continue

        caractere, tamanho = aberta
        fecha = (
            casou is not None
            and casou.group("marca")[0] == caractere
            and len(casou.group("marca")) >= tamanho
            and not casou.group("resto").strip()
        )
        if fecha:
            aberta = None
            pendente = []
        else:
            pendente.append((numero, linha))

    # Cerca sem fechamento nao remove nada: remover comeria o resto do texto, e
    # com ele o que vinha depois.
    fora.extend(pendente)
    return fora


def sem_blocos_de_codigo(corpo: str) -> str:
    """Tira os blocos cercados antes de procurar os rotulos.

    Citar o template e a regra dentro de um bloco de codigo e como as pessoas
    citam de verdade, e PR que mexe nesta regra e justamente quem mais cita. A
    alternativa seria pedir que ninguem escreva o rotulo literal — disciplina,
    que e o que este projeto troca por estrutura sempre que da.

    Nao afrouxa nada: rotulo repetido em PROSA continua reprovando, que e o caso
    em que a ambiguidade e real.

    A varredura mora em `linhas_fora_de_blocos`; isto so junta o texto.
    """
    return "\n".join(linha for _, linha in linhas_fora_de_blocos(corpo))
