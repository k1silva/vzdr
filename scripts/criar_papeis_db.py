"""Cria o papel da aplicacao no Postgres local, de forma idempotente.

O script de init do container so roda na primeira subida, e a CI nem usa
docker-compose — ela sobe um service container. Entao a criacao do papel
precisa de um caminho que funcione em banco ja existente, e e este.

Nao roda contra banco remoto: reusa a mesma guarda dos testes (ver
`scripts/ambiente_db.py`). Senha de laboratorio, igual a do docker-compose.yml;
producao cria o papel pela operacao, com senha que nao mora em repositorio.
"""

from __future__ import annotations

import os
import sys

from scripts.ambiente_db import (
    BancoRecusadoError,
    conectar,
    dsn_verificado,
    mensagem_sem_banco,
)

PAPEL = "vzdr_app"
VARIAVEL_SENHA = "VZDR_SENHA_APP"

# Nao ha senha padrao. Senha padrao que funciona e como credencial de
# laboratorio chega em producao: ninguem percebe que nunca a trocou, porque
# nada nunca falhou. Se o papel ja existe, nao precisamos de senha nenhuma —
# so garantimos os atributos.
SEM_SENHA = f"""
{VARIAVEL_SENHA} nao esta definida e o papel {PAPEL} nao existe neste banco.

  Laboratorio com volume novo: `make db-down && make db-up` cria o papel pelo
  script de init, e nada mais e preciso.
  Banco ja existente ou CI: exporte {VARIAVEL_SENHA} com a senha de laboratorio
  (a mesma do docker-compose.yml).
"""

EXISTE = "select 1 from pg_roles where rolname = %s"


class SenhaAusenteError(Exception):
    """Papel precisa ser criado e ninguem disse com que senha."""


# `nobypassrls` e o ponto: um papel que ignora RLS transformaria a politica em
# decoracao, e o teste de isolamento passaria sem provar nada (ADR-0006).
AJUSTAR = f"alter role {PAPEL} with login nobypassrls"

# `create role` e comando utilitario: nao aceita parametro vinculado, entao a
# senha entra composta com psycopg.sql.Literal, que escapa. Isto so falha na
# primeira execucao num banco sem o papel — foi a CI que pegou, porque
# localmente o papel ja existia.
CRIAR = "create role {papel} with login password {senha} nobypassrls"


def senha_para_criar(senha: str | None) -> str:
    """A senha a usar, ou levanta se nao houver. Pura, para ter teste."""
    if not senha:
        raise SenhaAusenteError(SEM_SENHA)
    return senha


def main() -> int:
    import psycopg

    try:
        dsn = dsn_verificado(os.environ)
    except BancoRecusadoError as erro:
        print(f"criar_papeis_db: {erro}", file=sys.stderr)
        return 2

    try:
        conexao = conectar(os.environ, autocommit=True)
    except psycopg.Error as erro:
        print(mensagem_sem_banco(dsn, erro), file=sys.stderr)
        return 1

    try:
        with conexao.cursor() as cur:
            cur.execute(EXISTE, (PAPEL,))
            if cur.fetchone() is not None:
                cur.execute(AJUSTAR)
                print(f"papel {PAPEL} ja existia; atributos conferidos")
                return 0

            try:
                senha = senha_para_criar(os.environ.get(VARIAVEL_SENHA))
            except SenhaAusenteError as erro:
                print(f"criar_papeis_db: {erro}", file=sys.stderr)
                return 2

            cur.execute(
                psycopg.sql.SQL(CRIAR).format(
                    papel=psycopg.sql.Identifier(PAPEL),
                    senha=psycopg.sql.Literal(senha),
                )
            )
    except psycopg.Error as erro:
        # Nao e "sem banco": conectamos. E falha ao mexer no papel, e o erro
        # cru do Postgres vai inteiro (P8).
        print(f"criar_papeis_db: falhou ao criar ou ajustar {PAPEL}.\n  {erro!r}", file=sys.stderr)
        return 1
    finally:
        conexao.close()

    print(f"papel {PAPEL} criado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
