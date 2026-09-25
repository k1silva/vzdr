"""Resolver token de servico em `Principal`.

Criar, listar, revogar e rotacionar sao de `core-007`. Aqui esta o modelo e a
resolucao.

## O papel e lido na hora, nunca congelado

`token_servico` guarda o dono e o tenant, jamais o papel. O papel vive so em
`associacao_tenant`, e a resolucao o le a cada uso.

A chave composta do esquema ja garante o caso extremo — associacao some, token
morre, em cascata. Mas o caso comum nao e sumir, e **mudar**: o dono era `admin`
e virou `viewer`. A associacao continua existindo, a chave nao dispara, e a
unica coisa que tira a autoridade do token e esta leitura. Por isso ela tem
teste proprio: o teste da chave composta continuaria passando com o papel
congelado, e daria impressao de cobertura.

## O formato e o mesmo da sessao

`<tenant_id>.<segredo>`, pelo mesmo motivo: `token_servico` tem `tenant_id`,
logo tem RLS, e ler a linha exigiria o contexto que so se sabe lendo a linha.
Formato unico significa um analisador so e um caminho de codigo so.

## `ultimo_uso_em` e gravado na mesma instrucao, e condicionalmente

Gravar a cada resolucao tornaria o caminho de leitura mais quente do sistema um
caminho de escrita, com contencao na mesma linha. A gravacao so acontece quando
o valor guardado ja esta velho.

Duas consequencias, aceitas e escritas: acao que falha e desfaz leva o carimbo
junto — para "posso revogar sem quebrar nada?", uso que nao completou nao conta
mesmo —, e a resolucao passa a exigir transacao de leitura-escrita, que e o
obstaculo se um dia alguem quiser servir leitura por replica.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from vzdr.core.domain.tenancy import Papel, Principal
from vzdr.core.tenancy.autenticacao import (
    TokenInvalidoError,
    _abrir_contexto,
    _hash_do_token,
)

if TYPE_CHECKING:
    import psycopg

    Conexao = psycopg.Connection[Any]

#: Granularidade do carimbo de uso. Minutos respondem a pergunta da tela;
#: milissegundos custariam uma escrita por requisicao e nao responderiam nada
#: a mais.
JANELA_DE_USO = timedelta(minutes=5)

#: Resolucao e carimbo numa instrucao so. O `update` e condicional e nao
#: interfere no resultado: `alvo` e calculado do mesmo instantaneo.
_RESOLVER = """
with alvo as (
    select t.id, t.usuario_dono_id, t.tenant_id, a.papel
    from token_servico t
    join associacao_tenant a
      on a.usuario_id = t.usuario_dono_id and a.tenant_id = t.tenant_id
    where t.token_hash = %(hash)s
),
carimbo as (
    update token_servico t set ultimo_uso_em = now()
    from alvo
    where t.id = alvo.id
      and (t.ultimo_uso_em is null or t.ultimo_uso_em < now() - %(janela)s::interval)
)
select id, usuario_dono_id, tenant_id, papel from alvo
"""


def resolver(conexao: Conexao, token: str) -> Principal:
    """Devolve o `Principal` do token de servico, ou levanta.

    O principal sai com a origem `servico`, o dono em `usuario_id` e o papel
    **do dono, agora** — nunca o que valia quando o token foi emitido.
    """
    tenant, _, segredo = token.partition(".")
    if not segredo:
        raise TokenInvalidoError("malformado")
    try:
        tenant_id = UUID(tenant)
    except ValueError as erro:
        raise TokenInvalidoError("malformado") from erro

    with conexao.transaction(), conexao.cursor() as cur:
        _abrir_contexto(cur, tenant_id)
        cur.execute(
            _RESOLVER,
            {"hash": _hash_do_token(token), "janela": str(JANELA_DE_USO)},
        )
        linha = cur.fetchone()

    if linha is None:
        raise TokenInvalidoError("desconhecido")

    servico_id, dono_id, tenant_da_linha, papel = linha
    return Principal.de_servico(dono_id, servico_id, tenant_da_linha, Papel(papel))


__all__ = ["JANELA_DE_USO", "resolver"]
