"""Trocar de tenant sem digitar a senha de novo.

Papel e por tenant, entao um usuario com papel em dois tenants precisa ir de um
ao outro. Reautenticar a cada troca tornaria hostil justamente o caso de teste
central da spec.

Tres decisoes estao na spec, secao "Trocar de tenant: a cadeia de sessoes", e o
codigo aqui so as executa:

1. **A expiracao e herdada, e quem garante e o banco.** A chave estrangeira
   composta `(sessao_pai_id, expira_em) -> sessao (id, expira_em)` recusa filha
   com expiracao diferente. Este modulo copia o `expira_em` da mae porque e a
   unica coisa que o banco aceita — nao porque lembrou de copiar.
2. **A forma e cadeia.** A -> B -> C cria filha de B, nao irma de B sob A. No
   leque, revogar B deixaria C viva, e C nasceu de B.
3. **A verificacao do destino usa o proprio destino.** Conferir a associacao em
   B exige ler `associacao_tenant`, que tem RLS, e no contexto de A a linha de B
   esta escondida. Como o destino e conhecido, abre-se o contexto em B: zero
   linhas e exatamente "nao e membro". Sem conexao privilegiada.

A linha filha vive no tenant de destino e aponta para uma mae no de origem. Isso
atravessa a fronteira de proposito, e so funciona porque verificacao de
integridade referencial ignora RLS — e o que faz o cascade alcancar
descendentes em outros tenants.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any
from uuid import UUID

from vzdr.core.audit import registrar
from vzdr.core.domain.tenancy import Papel, Principal
from vzdr.core.tenancy.autenticacao import (
    SemAssociacaoNoTenantError,
    TokenExpiradoError,
    TokenInvalidoError,
    _abrir_contexto,
    _hash_do_token,
)
from vzdr.core.tenancy.repositorio import Repositorio

if TYPE_CHECKING:
    import psycopg

    Conexao = psycopg.Connection[Any]


class TokenDeServicoNaoTrocaError(Exception):
    """Token de servico e emitido para um tenant e nele fica.

    Automacao que atende dois tenants tem dois tokens, e isso e desejavel: a
    auditoria diz qual agiu. Deixar um token de servico saltar de tenant
    apagaria essa distincao.
    """


def trocar_tenant(conexao: Conexao, token: str, tenant_destino: UUID) -> str:
    """Devolve o token da sessao no tenant de destino.

    Nao pede senha: a autoridade vem da sessao que ja existe.
    """
    tenant_origem, _, segredo = token.partition(".")
    if not segredo:
        raise TokenInvalidoError("malformado")
    try:
        origem_id = UUID(tenant_origem)
    except ValueError as erro:
        raise TokenInvalidoError("malformado") from erro

    if origem_id == tenant_destino:
        # Nao e erro nem operacao: devolver a mesma sessao seria mentir sobre
        # ter criado uma, e criar um nivel a toa engordaria a cadeia por nada.
        #
        # E NAO e auditado, de proposito: nada mudou. Registrar
        # `tenancy.tenant_trocado` aqui contaria uma troca que nao houve, e
        # auditoria que descreve o que nao aconteceu e pior que auditoria
        # ausente — quem investiga passa a ter de filtrar o ruido.
        return token

    with conexao.transaction(), conexao.cursor() as cur:
        # Passo 1, no contexto da ORIGEM: a sessao que autoriza a troca.
        _abrir_contexto(cur, origem_id)
        hash_do_token = _hash_do_token(token)
        # `expira_em <= now()` vem do banco, na mesma consulta: comparar com o
        # relogio do processo introduziria desvio entre maquinas.
        cur.execute(
            "select id, usuario_id, expira_em, expira_em <= now() "
            "from sessao where token_hash = %s",
            (hash_do_token,),
        )
        linha = cur.fetchone()
        if linha is None:
            # Pode ser token de servico: ele nao vive em `sessao`. A recusa e
            # feita AQUI, e nao por uma funcao que alguem precise lembrar de
            # chamar antes.
            cur.execute("select 1 from token_servico where token_hash = %s", (hash_do_token,))
            if cur.fetchone() is not None:
                raise TokenDeServicoNaoTrocaError(
                    "token de servico e emitido para um tenant e nele fica; "
                    "automacao que atende dois tenants tem dois tokens, e a "
                    "auditoria diz qual agiu"
                )
            raise TokenInvalidoError("desconhecida")

        mae_id, usuario_id, expira_em, expirada = linha
        if expirada:
            raise TokenExpiradoError("sessao expirada")

        # Passo 2, no contexto do DESTINO: a associacao que autoriza a entrada.
        _abrir_contexto(cur, tenant_destino)
        cur.execute(
            "select papel from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario_id, tenant_destino),
        )
        associacao = cur.fetchone()
        if associacao is None:
            raise SemAssociacaoNoTenantError(f"usuario nao tem papel no tenant {tenant_destino}")

        novo_token = f"{tenant_destino}.{secrets.token_urlsafe(32)}"
        cur.execute(
            "insert into sessao "
            "(token_hash, usuario_id, tenant_id, expira_em, sessao_pai_id) "
            "values (%s, %s, %s, %s, %s)",
            # `expira_em` e o da mae. Passar outro valor e recusado pelo banco.
            (_hash_do_token(novo_token), usuario_id, tenant_destino, expira_em, mae_id),
        )

        # A troca e auditada no tenant de DESTINO, com a origem no detalhe: e
        # la que o acesso passa a valer. O contexto ja e o do destino.
        (papel,) = associacao
        repositorio = Repositorio(
            conexao, Principal.de_usuario(usuario_id, tenant_destino, Papel(papel))
        )
        with repositorio.transacao() as r:
            registrar(
                r,
                "tenancy.tenant_trocado",
                f"tenant:{tenant_destino}",
                {"tenant_de_origem": str(origem_id)},
            )

        return novo_token


__all__ = [
    "TokenDeServicoNaoTrocaError",
    "trocar_tenant",
]
