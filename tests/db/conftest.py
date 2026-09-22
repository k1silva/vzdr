"""Fixtures dos testes que exigem PostgreSQL.

Sem banco, estes testes **falham** — nao sao pulados. Um teste de isolamento de tenant
que se pula em silencio da a mesma saida verde de um que passou, e e exatamente a
garantia que a core-001 nao pode ter frouxa.
"""

from __future__ import annotations

import os

import pytest

from tests.db.ambiente import dsn_de, mensagem_sem_banco, verificar_alvo


@pytest.fixture(scope="session")
def dsn() -> str:
    alvo = dsn_de(os.environ)
    verificar_alvo(alvo, os.environ)
    return alvo


@pytest.fixture()
def conexao(dsn: str):
    """Conexao com o Postgres local, uma por teste, sempre fechada no fim."""
    try:
        import psycopg
    except ImportError as erro:  # pragma: no cover - so sem dependencia instalada
        pytest.fail(f"psycopg nao esta instalado. Rode: make setup\n  Erro original: {erro!r}")

    try:
        conn = psycopg.connect(dsn)
    except Exception as erro:
        pytest.fail(mensagem_sem_banco(dsn, erro))

    try:
        yield conn
    finally:
        conn.close()
