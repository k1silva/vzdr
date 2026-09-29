#!/usr/bin/env python3
"""A declaracao de revisao do PR foi respondida.

O nome deste arquivo diz o que ele faz, e so isso. Ele **nao** verifica que a
revisao aconteceu: "k1silva leu o diff" nao e fato do repositorio, e nenhum
checador vai torna-lo um. A doenca deste projeto nao e checador que verifica
pouco — e checador que afirma mais do que verifica.

O que ele verifica e fato: as tres linhas do template foram respondidas, ou
ficaram com o texto que veio pronto.

Nao entra no `make invariants`, que e deterministico e roda sem rede. Este
precisa do corpo do PR, entao tem alvo proprio e job proprio, e **falha** quando
nao recebe entrada — passar em silencio sem corpo seria ausencia de verificacao
com cara de aprovacao.
"""

import os
import re
import sys
from pathlib import Path

from blocos_markdown import sem_blocos_de_codigo

#: (rotulo, o que uma resposta valida parece)
CAMPOS = (
    ("Revisou o diff", re.compile(r"[A-Za-z0-9]")),
    ("Humano leu o diff", re.compile(r"\b(sim|nao|não)\b", re.IGNORECASE)),
    ("Clique do merge delegado", re.compile(r"\b(sim|nao|não)\b", re.IGNORECASE)),
)

#: O que o template traz por responder. Achar isto e achar campo nao respondido.
POR_RESPONDER = re.compile(r"<\s*(quem|sim/nao|preencher)\s*>", re.IGNORECASE)


def _linhas_do_campo(corpo: str, rotulo: str) -> list[str]:
    """TODAS as ocorrencias do rotulo, nao a primeira.

    Corpo de PR e markdown livre, e neste projeto ele frequentemente CITA trecho
    de documento — inclusive a propria regra e o proprio template. Com duas
    ocorrencias, pegar a primeira e escolher em silencio: se a citada vier antes
    e estiver respondida num exemplo, um PR que nao respondeu passa.

    Quem chama trata mais de uma como falha. Ambiguidade e falha, nao escolha.
    """
    padrao = re.compile(
        # `[ \t]*` e nao `\s*`: `\s` casa quebra de linha, e ai um campo vazio
        # engole a linha seguinte e le a resposta DELA. Um PR com o primeiro
        # campo em branco passaria, lendo o segundo duas vezes.
        # Sem espaco antes do marcador: a declaracao de verdade mora na
        # margem, e bloco de codigo INDENTADO e a outra forma de citar em
        # markdown — cerca sozinha nao o alcanca.
        r"^[-*]?[ \t]*\**" + re.escape(rotulo) + r"\**[ \t]*:[ \t]*(?P<resposta>.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    return [m.group("resposta").strip() for m in padrao.finditer(corpo)]


def verificar(corpo: str) -> list[str]:
    """Devolve a lista de falhas; vazia quer dizer declaracao respondida."""
    corpo = sem_blocos_de_codigo(corpo)
    falhas = []
    for rotulo, resposta_valida in CAMPOS:
        achadas = _linhas_do_campo(corpo, rotulo)
        if not achadas:
            falhas.append(f"{rotulo!r}: a linha nao esta no corpo do PR")
            continue
        if len(achadas) > 1:
            falhas.append(
                f"{rotulo!r}: aparece {len(achadas)} vezes no corpo; a declaracao "
                "tem que ser inequivoca"
            )
            continue
        resposta = achadas[0]
        limpa = resposta.strip("`* ")
        if not limpa:
            falhas.append(f"{rotulo!r}: sem resposta")
        elif POR_RESPONDER.search(limpa):
            falhas.append(f"{rotulo!r}: ainda com o texto do template ({limpa!r})")
        elif not resposta_valida.search(limpa):
            falhas.append(f"{rotulo!r}: resposta nao reconhecida ({limpa!r})")
    return falhas


def _corpo_da_entrada(argv: list[str]) -> str:
    """O corpo vem de arquivo (argv) ou da variavel CORPO_DO_PR.

    Sem nenhum dos dois e erro, nao 'nada a fazer'. Um job que deixou de passar
    a entrada apareceria como sucesso, e ausencia de check e indistinguivel de
    aprovacao em quase toda interface.
    """
    if len(argv) > 1:
        return Path(argv[1]).read_text(encoding="utf-8")
    do_ambiente = os.environ.get("CORPO_DO_PR")
    if do_ambiente is not None:
        return do_ambiente
    raise SystemExit(
        "sem corpo de PR para conferir: passe um arquivo como argumento ou "
        "defina CORPO_DO_PR. Este checador nao passa sem entrada."
    )


def main() -> int:
    falhas = verificar(_corpo_da_entrada(sys.argv))
    if falhas:
        print("declaracao de revisao incompleta:")
        for falha in falhas:
            print(f"  - {falha}")
        print("\nVer AGENTS.md, 'Branch e PR'. O checador confere que as linhas")
        print("foram respondidas — nao que a revisao aconteceu.")
        return 1
    print("declaracao de revisao respondida, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
