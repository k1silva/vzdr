"""Conceder papel dentro de um tenant.

**Uma regra de autorizacao, nao duas:** `admin` daquele tenant. O operador de
plataforma nao entra aqui. Conceder o primeiro papel de um tenant nao e uma
concessao com regra especial — e parte de `criar_tenant`, operacao diferente,
com outro autor e outro evento. Duas regras para a mesma operacao e o que emerge
do codigo e ninguem consegue reler um ano depois.

## Um lugar so decide entre os dois eventos

`tenancy.papel_concedido` e `tenancy.papel_autoconcedido` sao decididos aqui,
comparando quem concede com quem recebe. Nao e responsabilidade do chamador
lembrar: chamador que lembra e chamador que esquece.

Auto-concessao ter tipo proprio e o que permite alertar sobre ela sem varrer o
log. Nada impede o ato — impedir seria teatro, ja que quem pode conceder pode
criar um segundo admin e os dois se concederem mutuamente. O que a auditoria faz
e nao deixar isso passar como concessao comum.

## O tenant vem do principal

Nao ha parametro de tenant. Ele sai de `quem.tenant_id`, porque um parametro que
precisa ser igual ao do principal e um parametro que pode discordar dele.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from vzdr.core.audit import registrar
from vzdr.core.domain.tenancy import Acao, Papel, Principal, pode
from vzdr.core.tenancy.repositorio import Repositorio

if TYPE_CHECKING:
    import psycopg

    Conexao = psycopg.Connection[Any]

EVENTO_CONCEDIDO = "tenancy.papel_concedido"
EVENTO_AUTOCONCEDIDO = "tenancy.papel_autoconcedido"
EVENTO_NEGADO = "tenancy.concessao_negada"


class ConcessaoNegadaError(Exception):
    """Quem pediu nao tem `admin` neste tenant."""


def evento_de(quem: Principal, beneficiario: UUID) -> str:
    """O tipo do evento. Puro, para ter teste sem banco.

    Quem concede e quem recebe sendo o mesmo principal e auto-concessao — e
    confundir os dois esconde a unica concessao que ninguem revisou dentro do
    volume das que alguem revisou.
    """
    if quem.usuario_id == beneficiario:
        return EVENTO_AUTOCONCEDIDO
    return EVENTO_CONCEDIDO


def conceder_papel(conexao: Conexao, quem: Principal, beneficiario: UUID, papel: Papel) -> None:
    """Concede ou altera o papel de `beneficiario` no tenant de `quem`."""
    repositorio = Repositorio(conexao, quem)

    if not pode(quem, Acao.GERIR_USUARIOS):
        # A tentativa negada entra na auditoria do proprio tenant: quem tentou
        # e membro dele, e e la que a tentativa interessa.
        with repositorio.transacao() as r:
            registrar(
                r,
                EVENTO_NEGADO,
                f"usuario:{beneficiario}",
                {"papel_pedido": papel.value, "papel_de_quem_pediu": _papel_de(quem)},
            )
        raise ConcessaoNegadaError(f"conceder papel exige admin no tenant {quem.tenant_id}")

    with repositorio.transacao() as r, conexao.cursor() as cur:
        cur.execute(
            "select papel from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (beneficiario, quem.tenant_id),
        )
        linha = cur.fetchone()
        anterior = linha[0] if linha else None

        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) "
            "values (%s, %s, %s) "
            "on conflict (usuario_id, tenant_id) do update set papel = excluded.papel",
            (beneficiario, quem.tenant_id, papel.value),
        )

        detalhe = {"papel": papel.value}
        if anterior is not None:
            detalhe["papel_anterior"] = anterior
        registrar(r, evento_de(quem, beneficiario), f"usuario:{beneficiario}", detalhe)


def _papel_de(principal: Principal) -> str:
    return principal.papel.value if principal.papel else "sem papel"


__all__ = [
    "EVENTO_AUTOCONCEDIDO",
    "EVENTO_CONCEDIDO",
    "EVENTO_NEGADO",
    "ConcessaoNegadaError",
    "conceder_papel",
    "evento_de",
]
