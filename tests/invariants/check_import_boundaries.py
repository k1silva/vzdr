#!/usr/bin/env python3
"""Falha o build se as fronteiras entre modulos forem violadas.

P11: features nao conhecem umas as outras; o nucleo nao conhece as features.
"""
import ast
import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


def modulo_de(arquivo: Path) -> str:
    """Devolve o modulo vzdr.* a partir do caminho sob src/."""
    partes = arquivo.parts
    if "src" not in partes:
        return ""
    i = partes.index("src")
    return ".".join(partes[i + 1:]).removesuffix(".py").removesuffix(".__init__")


def imports_de(arquivo: Path):
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for a in no.names:
                yield no.lineno, a.name
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            yield no.lineno, no.module


def feature_de(mod: str) -> str:
    """vzdr.tools.dr.x -> 'dr'; qualquer outra coisa -> ''."""
    p = mod.split(".")
    if len(p) >= 3 and p[0] == "vzdr" and p[1] == "tools":
        return p[2]
    return ""


def main() -> int:
    if not PACKAGES.exists():
        print("aviso: packages/ ainda nao existe, nada a checar")
        return 0

    falhas = []
    for arquivo in PACKAGES.rglob("*.py"):
        origem = modulo_de(arquivo)
        if not origem.startswith("vzdr."):
            continue
        origem_feature = feature_de(origem)
        origem_nucleo = origem.startswith("vzdr.core.")

        for linha, alvo in imports_de(arquivo):
            alvo_feature = feature_de(alvo)

            if origem_nucleo and alvo.startswith("vzdr.tools."):
                falhas.append(
                    f"{arquivo}:{linha}: nucleo importando feature "
                    f"('{origem}' -> '{alvo}'). O nucleo nao conhece as features (P11)."
                )

            if origem_feature and alvo_feature and alvo_feature != origem_feature:
                falhas.append(
                    f"{arquivo}:{linha}: feature importando outra feature "
                    f"('{origem}' -> '{alvo}'). Use eventos (P11)."
                )

    if falhas:
        print("Fronteiras violadas:")
        for f in falhas:
            print("  " + f)
        return 1

    print("fronteiras entre modulos, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
