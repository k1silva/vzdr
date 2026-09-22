#!/usr/bin/env python3
"""Falha o build se alguma migracao criar tabela sem tenant_id.

P9: tenant_id em toda tabela, desde a primeira migracao.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "migrations"

ISENTAS = {"alembic_version", "tenants", "schema_migrations"}

PADRAO = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?([\w.\"]+)(.*?);",
    re.IGNORECASE | re.DOTALL,
)


def main() -> int:
    if not ROOT.exists():
        print(f"aviso: {ROOT} ainda nao existe, nada a checar")
        return 0

    falhas = []
    for arquivo in sorted(ROOT.rglob("*.sql")):
        texto = arquivo.read_text(encoding="utf-8")
        for m in PADRAO.finditer(texto):
            nome = m.group(1).strip('"').split(".")[-1].lower()
            corpo = m.group(2)
            if nome in ISENTAS:
                continue
            if "tenant_id" not in corpo.lower():
                falhas.append(f"{arquivo.name}: tabela '{nome}' sem tenant_id")

    if falhas:
        print("P9 violado — tenant_id em toda tabela:")
        for f in falhas:
            print("  " + f)
        return 1

    print("tenant_id presente em todas as tabelas, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
