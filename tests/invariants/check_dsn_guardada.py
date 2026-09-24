#!/usr/bin/env python3
"""Falha o build se alguem abrir conexao com o banco fora da porta unica.

Ha uma senha de laboratorio escrita em `scripts/ambiente_db.py`. Ela e segura
por um motivo estreito: as DSN apontam para localhost e `verificar_alvo` recusa
qualquer outro host. Isso vale enquanto NENHUM caminho conseguir conectar sem
passar por la — e "todo mundo lembra de chamar a guarda" e disciplina, nao
garantia. Ja perdemos essa aposta quatro vezes nesta fatia.

Entao: `psycopg.connect` so pode aparecer em scripts/ambiente_db.py. Quem
precisa de conexao chama `conectar()`, que resolve, verifica e conecta numa
operacao so.

## Ate onde este checador alcanca

Ele le o fonte com `ast`, sem executar nada. Medido, nao suposto:

| Forma | Pega? |
|---|---|
| `psycopg.connect(...)` | sim |
| `from psycopg import connect` e `connect(...)` | sim |
| `import psycopg as p` e `p.connect(...)` | sim |
| `getattr(psycopg, "connect")(...)` | **nao** |
| `psycopg.__dict__["connect"](...)` | **nao** |
| qualquer `x.connect(...)`, de qualquer objeto | sim — e falso positivo |

Ou seja: ele barra o acesso direto e escorrega no acesso dinamico. Isso e
deliberado — nenhuma analise estatica de Python fecha acesso dinamico, e tentar
produziria um checador que ninguem entende. O que ele garante e que ninguem
abre conexao *por distracao*; ele nao impede quem esteja decidido a contornar.

A ultima linha tambem importa: como ele casa por nome, qualquer metodo chamado
`connect` reprova. Se um dia isso incomodar, a saida e casar tambem o modulo de
origem, nao afrouxar a regra.
"""

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PASTAS = ("packages", "scripts", "tests")

# O unico arquivo que pode abrir conexao. Acrescentar nome aqui e decidir que
# existe um segundo caminho — pense duas vezes.
PORTA_UNICA = "scripts/ambiente_db.py"

PORTA = "conectar()"


def _e_connect(no: ast.AST) -> bool:
    """psycopg.connect(...) ou connect(...) importado de psycopg."""
    if not isinstance(no, ast.Call):
        return False
    alvo = no.func
    if isinstance(alvo, ast.Attribute):
        return alvo.attr == "connect"
    return isinstance(alvo, ast.Name) and alvo.id == "connect"


def verificar(raiz: Path) -> list:
    falhas = []
    for pasta in PASTAS:
        base = raiz / pasta
        if not base.exists():
            continue
        for arquivo in sorted(base.rglob("*.py")):
            relativo = arquivo.relative_to(raiz).as_posix()
            if relativo == PORTA_UNICA:
                continue
            try:
                arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=relativo)
            except SyntaxError as erro:  # pragma: no cover - arquivo quebrado
                falhas.append(f"{relativo}: nao foi possivel ler ({erro})")
                continue
            for no in ast.walk(arvore):
                if _e_connect(no):
                    falhas.append(
                        f"{relativo}:{no.lineno}: abre conexao por fora de "
                        f"{PORTA_UNICA}.\n"
                        f"      Use {PORTA}, que resolve a DSN e passa pela guarda "
                        f"de host na mesma operacao.\n"
                        f"      Conexao direta ignora `verificar_alvo` e pode "
                        f"alcancar um banco que nao e esta maquina."
                    )
    return falhas


def main() -> int:
    falhas = verificar(RAIZ)
    if falhas:
        print("Conexao com o banco fora da porta unica:")
        for f in falhas:
            print("  " + f)
        return 1
    print(f"toda conexao passa por {PORTA_UNICA}, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
