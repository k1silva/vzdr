"""Fixtures dos testes que exigem PostgreSQL.

Sem banco, estes testes **falham** — nao sao pulados. Um teste de isolamento de tenant
que se pula em silencio da a mesma saida verde de um que passou, e e exatamente a
garantia que a core-001 nao pode ter frouxa.
"""

from __future__ import annotations

import os

import pytest

from scripts.ambiente_db import dsn_de, mensagem_sem_banco, verificar_alvo


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


@pytest.fixture()
def esquema_limpo(conexao):
    """Um schema so para o teste, derrubado no fim.

    Migracao cria e apaga tabela; sem isolamento, um teste enxerga o esquema que
    o outro deixou e a suite passa a depender da ordem.
    """
    import uuid

    conexao.autocommit = True
    nome = f"teste_{uuid.uuid4().hex[:12]}"
    with conexao.cursor() as cur:
        cur.execute(f'create schema "{nome}"')
        cur.execute(f'set search_path to "{nome}"')
    try:
        yield nome
    finally:
        with conexao.cursor() as cur:
            cur.execute(f'drop schema if exists "{nome}" cascade')
