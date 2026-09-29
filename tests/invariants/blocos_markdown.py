"""Leitura de markdown comum aos checadores.

Existe para que dois checadores nao tenham dois removedores de bloco de codigo.
Onde dois caminhos fazem o mesmo trabalho, o defeito mora no lado mais solto —
e um removedor que aprende a grafia `~~~` enquanto o outro nao aprende e
exatamente isso. Ver AGENTS.md.
"""

import re

__all__ = ["sem_blocos_de_codigo"]

#: Cerca, pelo CommonMark: crase ou til, tres ou mais, com ate tres espacos de
#: indentacao. As tres variacoes importam e nenhuma e exotica — `~~~` e o que se
#: escolhe quando o conteudo tem crase, e quatro crases e o jeito normal de citar
#: um bloco que ja contem tres. O template tem as duas coisas.
_CERCA = re.compile(r"^(?P<ind>[ ]{0,3})(?P<marca>`{3,}|~{3,})(?P<resto>.*)$")


def sem_blocos_de_codigo(corpo: str) -> str:
    """Tira os blocos cercados antes de procurar os rotulos.

    Citar o template e a regra dentro de um bloco de codigo e como as pessoas
    citam de verdade, e PR que mexe nesta regra e justamente quem mais cita. A
    alternativa seria pedir que ninguem escreva o rotulo literal — disciplina,
    que e o que este projeto troca por estrutura sempre que da.

    Nao afrouxa nada: rotulo repetido em PROSA continua reprovando, que e o caso
    em que a ambiguidade e real.

    Varredor em vez de uma expressao regular so porque o fechamento depende da
    abertura — mesmo caractere, e pelo menos o mesmo tanto. Retrovisor com
    "pelo menos N" nao e expressavel em `re`, e a alternativa seria casar `{3}`
    fixo e deixar as outras grafias vazarem, que e cobrir metade.
    """
    fora: list[str] = []
    pendente: list[str] = []
    aberta: tuple[str, int] | None = None

    for linha in corpo.splitlines():
        casou = _CERCA.match(linha)
        if aberta is None:
            if casou is not None:
                marca = casou.group("marca")
                aberta = (marca[0], len(marca))
                pendente = [linha]
            else:
                fora.append(linha)
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
            pendente.append(linha)

    # Cerca sem fechamento nao remove nada: remover comeria o resto do corpo, e
    # com ele a declaracao de verdade.
    fora.extend(pendente)
    return "\n".join(fora)
