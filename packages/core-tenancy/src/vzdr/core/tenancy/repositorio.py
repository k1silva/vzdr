"""Acesso a dado de tenant, com o filtro por construcao.

Duas camadas protegem o isolamento, e elas sao independentes de proposito:

1. **este repositorio**, que injeta `tenant_id = <do principal>` em toda
   consulta e recusa escrita para outro tenant;
2. **a RLS no Postgres** (ADR-0006), que vale para qualquer consulta, venha
   daqui ou nao.

A armadilha de ter as duas: um repositorio que ESQUECA o filtro passa em todos
os testes, porque a RLS cobre o erro. Defesa em profundidade vira deteccao
zero — ninguem descobre que esta camada quebrou ate alguem consultar por um
caminho sem RLS. Por isso `tests/db/test_repositorio.py` mede cada camada
SOZINHA: o filtro daqui pela conexao do dono, onde a RLS nao se aplica; e a RLS
por consulta crua, sem este repositorio.

O repositorio nao faz o `SET LOCAL` por conta propria em cada consulta: quem
abre a transacao e `transacao()`, e e ali que o contexto nasce e morre. Contexto
amarrado a transacao e o que impede o tenant de grudar na conexao devolvida ao
pool.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from psycopg import sql

from vzdr.core.domain.tenancy import Principal

if TYPE_CHECKING:
    import psycopg

    Conexao = psycopg.Connection[Any]

VARIAVEL_DE_CONTEXTO = "vzdr.tenant_id"


class PrincipalSemTenantError(Exception):
    """Principal de plataforma, ou sem tenant ativo, pedindo dado de tenant.

    E a segunda invariante de specs/core-001-tenancy/spec.md, aqui em codigo:
    o papel de plataforma nao le nem escreve dado de tenant. O esquema ja o
    impede de carregar um tenant_id; isto impede de tentar.
    """


class ForaDeTransacaoError(Exception):
    """Consulta pedida fora de `transacao()`, sem contexto de tenant.

    Sem o contexto, a RLS devolve ZERO LINHA em vez de erro — por desenho
    (ADR-0006). No nivel do dado isso e a mesma armadilha de sempre: resultado
    vazio e indistinguivel de "nao ha nada", e quem escreveu a consulta vai
    depurar a consulta, nunca o contexto.

    Entao o repositorio falha alto, na construcao da consulta, em vez de
    devolver um vazio plausivel.
    """


class TenantAlheioError(Exception):
    """Escrita com tenant_id diferente do principal.

    A RLS tambem barraria, com erro de politica. Esta excecao existe para o
    erro aparecer com o nome do problema, e nao como negativa do banco.
    """


class Repositorio:
    """Toda leitura e escrita de dado de tenant passa por aqui."""

    def __init__(self, conexao: Conexao, principal: Principal) -> None:
        if principal.plataforma or principal.tenant_id is None:
            raise PrincipalSemTenantError(
                "principal de plataforma nao le nem escreve dado de tenant; "
                "para isso precisa de papel concedido dentro daquele tenant"
            )
        self._conexao = conexao
        self._principal = principal
        # Conta aninhamento: `transacao()` dentro de `transacao()` e savepoint,
        # e o contexto continua valendo ate a mais externa fechar.
        self._profundidade = 0

    @property
    def principal(self) -> Principal:
        return self._principal

    @property
    def tenant_id(self) -> Any:
        return self._principal.tenant_id

    @contextmanager
    def transacao(self) -> Iterator[Repositorio]:
        """Transacao com o contexto de tenant amarrado a ela.

        `set_config(..., true)` e o `SET LOCAL`: o valor morre no fim da
        transacao. Com `false` ele gruda na conexao, ela volta ao pool e atende
        a requisicao seguinte, de outro tenant.
        """
        with self._conexao.transaction(), self._conexao.cursor() as cur:
            cur.execute(
                "select set_config(%s, %s, true)",
                (VARIAVEL_DE_CONTEXTO, str(self.tenant_id)),
            )
            self._profundidade += 1
            try:
                yield self
            finally:
                self._profundidade -= 1

    def _exigir_contexto(self, operacao: str) -> None:
        if self._profundidade == 0:
            raise ForaDeTransacaoError(
                f"{operacao} pedido fora de transacao(). Sem contexto de tenant a "
                f"RLS devolve zero linha em vez de erro, e um vazio plausivel "
                f"manda voce depurar a consulta em vez do contexto. "
                f"Envolva em `with repositorio.transacao() as r:`."
            )

    def selecionar(
        self,
        tabela: str,
        colunas: Sequence[str],
        onde: str | None = None,
        parametros: Sequence[Any] = (),
    ) -> list[tuple[Any, ...]]:
        """Sempre com `tenant_id = <do principal>`. Nao ha como pedir sem."""
        self._exigir_contexto("select")
        consulta = sql.SQL("select {cols} from {tab} where tenant_id = %s").format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in colunas),
            tab=sql.Identifier(tabela),
        )
        valores: list[Any] = [self.tenant_id]
        if onde:
            consulta = consulta + sql.SQL(" and (") + sql.SQL(onde) + sql.SQL(")")
            valores.extend(parametros)
        with self._conexao.cursor() as cur:
            cur.execute(consulta, valores)
            return cur.fetchall()

    def inserir(self, tabela: str, valores: Mapping[str, Any]) -> None:
        """O `tenant_id` vem do principal, nunca do chamador."""
        self._exigir_contexto("insert")
        alheio = valores.get("tenant_id")
        if alheio is not None and str(alheio) != str(self.tenant_id):
            raise TenantAlheioError(
                f"tentou escrever em {tabela} com tenant_id={alheio}, "
                f"mas o principal e do tenant {self.tenant_id}"
            )

        dados = {**valores, "tenant_id": self.tenant_id}
        consulta = sql.SQL("insert into {tab} ({cols}) values ({marcas})").format(
            tab=sql.Identifier(tabela),
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in dados),
            marcas=sql.SQL(", ").join(sql.Placeholder() * len(dados)),
        )
        with self._conexao.cursor() as cur:
            cur.execute(consulta, list(dados.values()))
