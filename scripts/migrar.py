"""Aplica as migracoes SQL em ordem, uma transacao por arquivo.

Nao ha Alembic: as migracoes sao SQL versionado (deploy/README.md) e nao existe
ORM de onde geras-las. O preco de recusar a ferramenta e assumir o executor, e o
contrato dele tem que valer sempre:

- ordem lexicografica de nome;
- cada arquivo dentro de UMA transacao, DDL e registro juntos. Falha no meio nao
  deixa esquema parcial nem registro sem esquema;
- arquivo ja registrado e pulado, entao rodar duas vezes e inocuo;
- arquivo alterado depois de aplicado falha, em vez de aplicar outra coisa;
- migracao registrada que sumiu do disco falha;
- migracao nova que ordena antes de uma ja aplicada falha.

Uso, a partir da raiz do repositorio:

    python -m scripts.migrar

Nunca fora do ambiente local: AGENTS.md proibe, e `verificar_alvo` recusa DSN que
aponte para outra maquina.
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts.ambiente_db import (
    BancoRecusadoError,
    dsn_de,
    mensagem_sem_banco,
    verificar_alvo,
)

if TYPE_CHECKING:  # o driver so e preciso para aplicar; a decisao e pura
    import psycopg

    Conexao = psycopg.Connection[Any]

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "deploy" / "migrations"

# Sem tenant_id de proposito: e metadado do executor, nao dado de tenant.
# Consta da lista fechada de excecoes em specs/core-001-tenancy/spec.md.
TABELA = """
create table if not exists schema_migrations (
    nome        text        primary key,
    sha256      text        not null,
    aplicada_em timestamptz not null default now()
)
"""


class MigracaoAlteradaError(Exception):
    """Arquivo mudou depois de aplicado. O banco nao tem mais o que o disco diz."""


class MigracaoAusenteError(Exception):
    """Migracao registrada no banco sumiu do disco."""


class MigracaoForaDeOrdemError(Exception):
    """Migracao nova ordena antes de uma ja aplicada."""


class ConexaoSemAutocommitError(Exception):
    """A conexao precisa estar em autocommit para cada arquivo virar UMA transacao.

    Sem autocommit, o psycopg ja abre transacao no primeiro execute, e
    `conexao.transaction()` vira savepoint aninhado. Ai a falha de um arquivo nao
    desfaz o anterior, e uma migracao a meio caminho poderia ser commitada junto
    com a seguinte. O contrato do executor deixaria de valer em silencio.
    """


@dataclass(frozen=True)
class Migracao:
    nome: str
    caminho: Path
    sha256: str

    def sql(self) -> str:
        return self.caminho.read_text(encoding="utf-8")


def sha256_de(conteudo: str) -> str:
    return hashlib.sha256(conteudo.encode("utf-8")).hexdigest()


def descobrir(pasta: Path) -> list[Migracao]:
    """As migracoes do disco, em ordem lexicografica de nome."""
    if not pasta.exists():
        return []
    return [
        Migracao(
            nome=arq.name,
            caminho=arq,
            sha256=sha256_de(arq.read_text(encoding="utf-8")),
        )
        for arq in sorted(pasta.glob("*.sql"), key=lambda a: a.name)
    ]


def planejar(disponiveis: Sequence[Migracao], aplicadas: Mapping[str, str]) -> list[Migracao]:
    """O que falta aplicar, ou levanta se disco e banco divergiram.

    Recebe o estado em vez de consultar: a decisao e pura e testavel sem banco.
    """
    no_disco = {m.nome: m for m in disponiveis}

    for nome, sha in sorted(aplicadas.items()):
        migracao = no_disco.get(nome)
        if migracao is None:
            raise MigracaoAusenteError(
                f"'{nome}' esta registrada no banco e sumiu de {PASTA.name}/. "
                f"O historico do banco nao bate com o do repositorio."
            )
        if migracao.sha256 != sha:
            raise MigracaoAlteradaError(
                f"'{nome}' mudou depois de aplicada.\n"
                f"  no banco: {sha}\n"
                f"  no disco: {migracao.sha256}\n"
                f"Migracao aplicada e historico. Corrija com uma migracao nova."
            )

    pendentes = [m for m in disponiveis if m.nome not in aplicadas]
    if aplicadas and pendentes:
        ultima = max(aplicadas)
        atrasadas = [m.nome for m in pendentes if m.nome < ultima]
        if atrasadas:
            raise MigracaoForaDeOrdemError(
                f"{atrasadas} ordena(m) antes de '{ultima}', que ja foi aplicada. "
                f"Renomeie para depois dela — aplicar fora de ordem da um esquema "
                f"diferente do que a mesma pasta produz num banco limpo."
            )
    return pendentes


def garantir_tabela(conexao: Conexao) -> None:
    with conexao.transaction(), conexao.cursor() as cur:
        cur.execute(TABELA)


def aplicadas_em(conexao: Conexao) -> dict[str, str]:
    with conexao.cursor() as cur:
        cur.execute("select nome, sha256 from schema_migrations")
        return dict(cur.fetchall())


def aplicar(conexao: Conexao, migracao: Migracao) -> None:
    """DDL e registro na MESMA transacao. Ou os dois, ou nenhum."""
    with conexao.transaction(), conexao.cursor() as cur:
        # Sem parametros, o psycopg usa o protocolo simples e aceita varias
        # instrucoes num execute so — que e o que um arquivo de migracao tem.
        cur.execute(migracao.sql())
        cur.execute(
            "insert into schema_migrations (nome, sha256) values (%s, %s)",
            (migracao.nome, migracao.sha256),
        )


def migrar(conexao: Conexao, pasta: Path = PASTA) -> list[str]:
    """Aplica o que falta e devolve os nomes aplicados, em ordem."""
    if not conexao.autocommit:
        raise ConexaoSemAutocommitError(
            "conexao sem autocommit: cada arquivo tem que ser uma transacao propria, "
            "e sem autocommit o psycopg aninha savepoint em vez de abrir transacao."
        )
    garantir_tabela(conexao)
    pendentes = planejar(descobrir(pasta), aplicadas_em(conexao))
    for migracao in pendentes:
        aplicar(conexao, migracao)
    return [m.nome for m in pendentes]


def main() -> int:
    import psycopg

    dsn = dsn_de(os.environ)
    try:
        verificar_alvo(dsn, os.environ)
    except BancoRecusadoError as erro:
        print(f"migrar: {erro}", file=sys.stderr)
        return 2

    try:
        conexao = psycopg.connect(dsn)
    except psycopg.Error as erro:
        print(mensagem_sem_banco(dsn, erro), file=sys.stderr)
        return 1

    # Uma transacao por arquivo depende disto. Ver ConexaoSemAutocommitError.
    conexao.autocommit = True

    try:
        aplicadas = migrar(conexao)
    except (
        MigracaoAlteradaError,
        MigracaoAusenteError,
        MigracaoForaDeOrdemError,
        ConexaoSemAutocommitError,
    ) as erro:
        print(f"migrar: {erro}", file=sys.stderr)
        return 3
    except psycopg.Error as erro:
        # P8: o erro cru do Postgres, com o que ele disse. Nunca traduzido.
        print(f"migrar: falhou e nada foi aplicado desta vez.\n  {erro!r}", file=sys.stderr)
        return 1
    finally:
        conexao.close()

    if not aplicadas:
        print("nada a aplicar")
    for nome in aplicadas:
        print(f"aplicada {nome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
