#!/usr/bin/env python3
"""Um conceito tem uma definicao so, entre todas as specs.

E "tenant se diz uma vez" aplicado a documento, e a mesma regra do rotulo
repetido no corpo do PR: ambiguidade e falha, nao escolha silenciosa. Duas
definicoes do mesmo conceito podem discordar — e quando discordam, cada
implementacao segue uma, e a tela mente.

Nasceu de um caso real. A dr-001 definia `degradada` como conta derivada que
degrada a 2x o RPO, por tempo; a dr-006 a tinha como estado de maquina que
degrada "fora do RPO, ou quando o ultimo ciclo falhou". Duas pessoas leram as
duas specs e nenhuma notou.

O QUE CONTA COMO DEFINICAO — por estrutura, nunca por mencao. Busca por mencao
dispararia em toda citacao, e as pessoas parariam de ler o que este checador diz.

- item de lista que abre com o termo em crase e travessao:  - `termo` — ...
- titulo que abre com o termo em crase:                     ## `termo` ...

So em `specs/*/spec.md`. O plano e as tarefas implementam a spec, e restatear um
conceito ali e normal; a definicao mora na spec.

O QUE ELE NAO PEGA, e isto e o limite mais importante dele:

- **conceito definido em prosa**, nos dois lugares. E exatamente como `degradada`
  chegou ate aqui: ninguem escreveu duas entradas num bloco de definicoes, cada
  spec falou do conceito a seu modo. So pegou porque, por acaso, uma usava titulo
  e a outra lista. Isto nao tem conserto por checador sem cair em busca por
  mencao, e por isso existe a pergunta de revisao no AGENTS.md: "este conceito ja
  e definido em outro lugar?";
- **tabela.** 33 termos em crase aparecem como primeira coluna de tabela, nenhum
  repetido entre specs hoje. Tabela e usada tanto para definir quanto para
  comparar alternativas, e casa-la traria falso positivo que ensina a ignorar o
  checador;
- **termo sem crase**, como a secao "Conceitos" da dr-001 escreve.

E ignora blocos de codigo, pelo mesmo removedor do checador de declaracao.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

from blocos_markdown import linhas_fora_de_blocos

RAIZ = Path(__file__).resolve().parents[2]

_LISTA = re.compile(r"^[-*] `(?P<termo>[^`]+)` [—–] ")
_TITULO = re.compile(r"^#{2,6} `(?P<termo>[^`]+)`")


def definicoes(texto: str) -> list[tuple[str, int]]:
    """(termo, linha) de cada definicao estrutural fora de bloco de codigo.

    A linha e a do texto original, e vem do removedor — nao de comparar texto:
    uma definicao citada numa cerca tem o mesmo texto da verdadeira.
    """
    achadas = []
    for numero, linha in linhas_fora_de_blocos(texto):
        casou = _LISTA.match(linha) or _TITULO.match(linha)
        if casou:
            achadas.append((casou.group("termo"), numero))
    return achadas


def verificar(raiz: Path) -> list[str]:
    onde: dict[str, list[str]] = defaultdict(list)
    for spec in sorted(raiz.glob("specs/*/spec.md")):
        rotulo = spec.relative_to(raiz).as_posix()
        for termo, linha in definicoes(spec.read_text(encoding="utf-8")):
            onde[termo].append(f"{rotulo}:{linha}")
    falhas = []
    for termo, lugares in sorted(onde.items()):
        if len(lugares) > 1:
            falhas.append(f"`{termo}` definido {len(lugares)} vezes: " + ", ".join(lugares))
    return falhas


def main() -> int:
    falhas = verificar(RAIZ)
    if falhas:
        print("conceito com mais de uma definicao:")
        for falha in falhas:
            print(f"  - {falha}")
        print(
            "\nDefina num lugar so; nos outros, aponte para la. Se as definicoes"
            "\ndiscordam, arbitre por regra e nao escolhendo um vencedor — como"
            '\n"ciclo de vida e marcado, saude e derivada". Ver AGENTS.md.'
        )
        return 1
    print("definicao unica, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
