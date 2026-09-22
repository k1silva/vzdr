#!/usr/bin/env python3
"""Falha o build se vzdr.core.domain importar qualquer coisa de IO.

P do dominio: a logica tem que ser testavel sem hypervisor, sem rede e sem banco.
"""
import ast
import sys
from pathlib import Path

PROIBIDOS = {
    "libvirt", "socket", "requests", "httpx", "urllib", "sqlalchemy",
    "psycopg", "psycopg2", "asyncpg", "subprocess", "openstack", "boto3",
}

ROOT = Path(__file__).resolve().parents[2] / "packages" / "core-domain" / "src"


def main() -> int:
    if not ROOT.exists():
        print(f"aviso: {ROOT} ainda nao existe, nada a checar")
        return 0

    falhas = []
    for arquivo in ROOT.rglob("*.py"):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                nomes = [a.name.split(".")[0] for a in no.names]
            elif isinstance(no, ast.ImportFrom):
                nomes = [(no.module or "").split(".")[0]]
            else:
                continue
            for nome in nomes:
                if nome in PROIBIDOS:
                    falhas.append(f"{arquivo}:{no.lineno}: import proibido '{nome}'")

    if falhas:
        print("vzdr.core.domain tem que ser puro. Encontrado:")
        for f in falhas:
            print("  " + f)
        return 1

    print("vzdr.core.domain puro, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
