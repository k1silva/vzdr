"""A que Postgres falar, e quando se recusar a falar.

Uma regra, um lugar: serve os testes de `tests/db` e o executor de migracao. Quem
mais precisa dela e o executor, porque e dele que o AGENTS.md fala ao proibir
migracao fora do ambiente local.

Logica pura, sem conectar — o comportamento em falha e testavel sem banco nenhum.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

VARIAVEL = "VZDR_DATABASE_URL"
VARIAVEL_REMOTO = "VZDR_PERMITIR_BANCO_REMOTO"

# O mesmo que o docker-compose.yml sobe com `make db-up`.
DSN_LOCAL = "postgresql://vzdr:dev@localhost:5432/vzdr"

HOSTS_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1", "", None})


class BancoRecusadoError(Exception):
    """O DSN aponta para fora da maquina e ninguem autorizou."""


def dsn_de(ambiente: Mapping[str, str]) -> str:
    """O DSN do ambiente, ou o local do docker-compose."""
    return ambiente.get(VARIAVEL) or DSN_LOCAL


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
