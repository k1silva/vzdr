"""Apoio dos testes com banco: o contexto de tenant, como a aplicacao o usa."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID


@contextmanager
def contexto_de_tenant(conexao, tenant_id: UUID | str):
    """Transacao com `vzdr.tenant_id` amarrado a ela.

    O terceiro argumento de set_config e `is_local`: true amarra o valor a
    transacao. Com false, o valor gruda na conexao, ela volta ao pool e atende
    a requisicao seguinte — de outro tenant. E a pior falha possivel nesta
    area, e por isso ha teste so para ela.
    """
    with conexao.transaction(), conexao.cursor() as cur:
        cur.execute("select set_config('vzdr.tenant_id', %s, true)", (str(tenant_id),))
        yield cur
