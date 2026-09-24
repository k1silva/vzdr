"""A que Postgres falar, e quando se recusar a falar.

Uma regra, um lugar: serve os testes de `tests/db` e o executor de migracao. Quem
mais precisa dela e o executor, porque e dele que o AGENTS.md fala ao proibir
migracao fora do ambiente local.

Logica pura, sem conectar — o comportamento em falha e testavel sem banco nenhum.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:  # o driver so e preciso para conectar
    import psycopg

VARIAVEL = "VZDR_DATABASE_URL"
VARIAVEL_APP = "VZDR_DATABASE_URL_APP"
VARIAVEL_REMOTO = "VZDR_PERMITIR_BANCO_REMOTO"

# ATENCAO ao "consertar" isto.
#
# Sim, ha uma senha de laboratorio escrita aqui. Ela e segura por um motivo
# estreito: estas DSN apontam para localhost, e nada neste repositorio abre
# conexao sem passar por `verificar_alvo`, que recusa host que nao seja esta
# maquina. Uma credencial que so alcanca o proprio laptop nao da acesso a nada.
#
# Mover isto para variavel de ambiente PARECE mais seguro e e o contrario: a
# DSN passa a poder apontar para um banco real, e a senha de laboratorio vira
# a senha que alguem tentou em producao. Se for preciso mudar, mude junto a
# guarda, nao so o valor.
#
# Quem garante que nao ha atalho: tests/invariants/check_dsn_guardada.py, que
# falha se qualquer arquivo fora deste abrir conexao por conta propria.

# O mesmo que o docker-compose.yml sobe com `make db-up`.
DSN_LOCAL = "postgresql://vzdr:dev@localhost:5432/vzdr"

# O papel da aplicacao: nao e dono das tabelas e nao tem BYPASSRLS. E com ele
# que os testes de isolamento falam com o banco — rodar como dono provaria
# nada, porque dono ignora politica de RLS (ADR-0006).
DSN_LOCAL_APP = "postgresql://vzdr_app:dev@localhost:5432/vzdr"

HOSTS_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1", "", None})


class BancoRecusadoError(Exception):
    """O DSN aponta para fora da maquina e ninguem autorizou."""


def _resolver(ambiente: Mapping[str, str], app: bool) -> str:
    """So resolve, sem verificar. Privada de proposito: ver dsn_verificado."""
    if app:
        return ambiente.get(VARIAVEL_APP) or DSN_LOCAL_APP
    return ambiente.get(VARIAVEL) or DSN_LOCAL


def dsn_verificado(ambiente: Mapping[str, str], *, app: bool = False) -> str:
    """O DSN a usar, ja verificado.

    Resolver e verificar sao a MESMA operacao aqui, de proposito. Enquanto
    eram duas funcoes, "chamar a guarda" era disciplina de quem escrevia o
    proximo `main()` — e disciplina e exatamente o que falha quando um caminho
    novo aparece.
    """
    dsn = _resolver(ambiente, app)
    verificar_alvo(dsn, ambiente)
    return dsn


def conectar(
    ambiente: Mapping[str, str], *, app: bool = False, autocommit: bool = False
) -> psycopg.Connection[Any]:
    """A unica porta para abrir conexao neste repositorio.

    O checador de invariante recusa `psycopg.connect` em qualquer outro
    arquivo, entao nao existe caminho que escape de `verificar_alvo`.
    """
    import psycopg  # tardio: a logica acima e testavel sem o driver

    return psycopg.connect(dsn_verificado(ambiente, app=app), autocommit=autocommit)


def host_de(dsn: str) -> str | None:
    return urlsplit(dsn).hostname


def verificar_alvo(dsn: str, ambiente: Mapping[str, str]) -> None:
    """Recusa DSN nao-local sem autorizacao explicita.

    Os testes de `tests/db` e o executor de migracao criam e apagam esquema.
    AGENTS.md proibe rodar comando contra cluster de producao e migracao fora do
    ambiente local; um DSN apontando para outra maquina e a forma mais barata de
    furar isso sem perceber — nao exige erro de codigo, so uma variavel esquecida
    no shell.
    """
    host = host_de(dsn)
    if host in HOSTS_LOCAIS:
        return
    if ambiente.get(VARIAVEL_REMOTO) == "1":
        return
    raise BancoRecusadoError(
        f"{VARIAVEL} aponta para '{host}', que nao e esta maquina. Isto cria e "
        f"apaga esquema — rodar contra outro banco pode destruir dado. Se for "
        f"mesmo o que voce quer, exporte {VARIAVEL_REMOTO}=1."
    )


def mensagem_sem_banco(dsn: str, erro: Exception) -> str:
    """Mensagem de falha quando nao da para conectar. Preserva o erro cru (P8)."""
    return (
        f"Sem PostgreSQL em {dsn}.\n"
        f"  Suba com: make db-up\n"
        f"  Outro banco: exporte {VARIAVEL}\n"
        f"  Erro original: {erro!r}"
    )
