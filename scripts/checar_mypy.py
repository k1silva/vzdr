"""Roda o mypy e falha se alguma secao de configuracao nao casou com nada.

Por que isto existe: o mypy trata secao inerte como *nota*, nao como erro. Ele
sai com codigo 0 e escreve `unused section(s): module = [...]`. Quem le so o
codigo de saida — a CI, por exemplo — nao ve diferenca entre "verificado" e
"a regra nem chegou a ser aplicada".

Isso mordeu de verdade na TI1: remover `mypy_path` desligou o `--strict` de
`vzdr.core.domain`, o pacote mais critico do repositorio, sem uma linha
vermelha em lugar nenhum. A raiz de origem passou a sair de `MYPY_SRC`, no
Makefile, que virou ponto unico de falha: apagar aquela linha traz o buraco de
volta com a CI verde.

A guarda vale para QUALQUER secao orfa, nao so a do dominio. Renomear um pacote
e esquecer o override tem a mesma consequencia: uma regra que ninguem aplica e
ninguem percebe.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]

MARCA = "unused section"

EXPLICACAO = """
O mypy relatou secao de configuracao que nao casou com nenhum modulo.
Isso NAO e cosmetico: a regra daquela secao nao esta sendo aplicada, e o mypy
sai com codigo 0 assim mesmo.

Causas usuais:
  - MYPYPATH vazio ou errado: sem raiz de origem, `explicit_package_bases` nao
    monta o nome pontilhado de namespace package, e overrides como
    `vzdr.core.domain.*` deixam de casar. Ver MYPY_SRC no Makefile.
  - pacote renomeado ou removido, deixando o override orfao no pyproject.toml.
"""


def verificar_config(dados: Mapping[str, Any]) -> str:
    """Mensagem de erro se a propria guarda estiver desarmada, ou '' se ok."""
    mypy = dados.get("tool", {}).get("mypy", {})
    if mypy.get("warn_unused_configs") is not True:
        return (
            "warn_unused_configs precisa estar ligado em [tool.mypy]: e ele que "
            "faz o mypy relatar secao inerte. Desligado, esta guarda nao guarda "
            "nada."
        )
    return ""


def decidir(codigo: int, saida: str) -> tuple[int, str]:
    """Codigo de saida final e mensagem extra, a partir do que o mypy devolveu."""
    if MARCA in saida:
        return 1, EXPLICACAO
    return codigo, ""


def main(argv: Sequence[str]) -> int:
    erro = verificar_config(tomllib.loads((RAIZ / "pyproject.toml").read_text("utf-8")))
    if erro:
        print(f"checar_mypy: {erro}", file=sys.stderr)
        return 2

    proc = subprocess.run(  # noqa: S603 - argumentos vem do Makefile
        [sys.executable, "-m", "mypy", *argv],
        capture_output=True,
        text=True,
        cwd=RAIZ,
    )
    saida = proc.stdout + proc.stderr
    print(saida, end="", flush=True)

    codigo, extra = decidir(proc.returncode, saida)
    if extra:
        print(extra, file=sys.stderr)
    return codigo


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
