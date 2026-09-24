"""Fixtures dos testes que exigem PostgreSQL.

Sem banco, estes testes **falham** — nao sao pulados. Um teste de isolamento de tenant
que se pula em silencio da a mesma saida verde de um que passou, e e exatamente a
garantia que a core-001 nao pode ter frouxa.
"""

from __future__ import annotations

import os

import pytest

from scripts.ambiente_db import (
    dsn_app_de,
    dsn_de,
    mensagem_sem_banco,
    verificar_alvo,
)


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


@pytest.fixture(scope="session")
def dsn_app() -> str:
    alvo = dsn_app_de(os.environ)
    verificar_alvo(alvo, os.environ)
    return alvo


@pytest.fixture()
def conexao_app(dsn_app: str, esquema_limpo: str):
    """Conexao com o papel da aplicacao, no mesmo schema do teste.

    Nao e dono das tabelas e nao tem BYPASSRLS. Todo teste de privilegio ou de
    isolamento fala por aqui; `conexao` e o dono, e dono nao prova isolamento.
    """
    import psycopg

    try:
        conn = psycopg.connect(dsn_app)
    except Exception as erro:
        pytest.fail(mensagem_sem_banco(dsn_app, erro))

    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'set search_path to "{esquema_limpo}"')
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def esquema_migrado(conexao, esquema_limpo: str) -> str:
    """Schema temporario com a migracao 0001 aplicada."""
    from scripts.migrar import PASTA, migrar

    migrar(conexao, PASTA)
    return esquema_limpo
