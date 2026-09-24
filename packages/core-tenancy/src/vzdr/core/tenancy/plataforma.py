"""Papel de plataforma: criar tenants, e o operador que nasce sem autor.

O papel de plataforma existe fora do eixo de tenant. Nao tem `tenant_id`, nao
tem repositorio de tenant (o `Repositorio` recusa na construcao) e `pode()`
nega toda acao de tenant. Este modulo e o que ele faz.

## O tenant nasce com o primeiro admin

`criar_tenant` recebe quem sera o primeiro `admin` e cria as duas coisas na
mesma transacao: **tenant vazio nao e estado do sistema**. E o que dissolve a
pergunta "quem concede o primeiro papel num tenant recem-criado".

O operador abre contexto de tenant AQUI, e so aqui — num tenant que acabou de
criar, antes de existir qualquer coisa la dentro. Nao ha o que vazar. Nao existe
operacao que abra contexto num tenant com dado dentro, e `conceder_papel`
continua com uma regra so: `admin` daquele tenant.

## Auditado nos dois lugares

`tenancy.tenant_criado` em `auditoria_plataforma` diz que o operador agiu.
`tenancy.papel_concedido` na auditoria do tenant novo, com o operador como
autor, diz o que aconteceu la dentro — e e a linha que o cliente precisa ver.
Sem ela, o provedor poderia por alguem no tenant de um cliente sem que o cliente
conseguisse ver.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from vzdr.core.audit import registrar, registrar_plataforma
from vzdr.core.domain.tenancy import Acao, Papel, Principal, pode
from vzdr.core.tenancy.autenticacao import DURACAO_DA_SESSAO, _hash_do_token
from vzdr.core.tenancy.repositorio import Repositorio
from vzdr.core.tenancy.senha import hashear

if TYPE_CHECKING:
    import psycopg

    Conexao = psycopg.Connection[Any]


def _um_valor(cur: Any) -> Any:
    """A unica coluna da unica linha. `insert ... returning` sempre devolve uma;
    se nao devolver, algo mudou embaixo e e melhor saber alto."""
    linha = cur.fetchone()
    if linha is None:  # pragma: no cover - insert returning sempre devolve
        raise RuntimeError("esperava uma linha e nao veio nenhuma")
    return linha[0]


class PlataformaJaIniciadaError(Exception):
    """Ja existe papel de plataforma; o bootstrap nao tem mais o que fazer.

    A condicao e sobre o ESTADO, nao sobre o historico: se todos os operadores
    forem removidos por engano, o bootstrap volta a valer. Uma marca de "ja
    rodou" tornaria o sistema irrecuperavel, porque ninguem existiria para
    autorizar a criacao do primeiro de novo.
    """


class NaoEOperadorDePlataformaError(Exception):
    """Acao de plataforma pedida por quem nao tem o papel."""


def iniciar_plataforma(conexao: Conexao, email: str, senha: str) -> UUID:
    """Cria o primeiro operador de plataforma. **Nao e endpoint.**

    Nao existe caminho HTTP que alcance isto, nunca: e operacao local, com
    credencial de dono do banco, fora da aplicacao. Um endpoint de bootstrap
    teria de ser desligado depois, e "desligado depois" e a categoria de regra
    que esta spec vem eliminando.

    Escreve so em `usuarios`, `papel_plataforma` e `auditoria_plataforma` —
    todas fora do eixo de tenant. Se um dia precisar tocar tabela com
    `tenant_id`, o desenho esta errado: nao existe tenant ainda.
    """
    with conexao.transaction(), conexao.cursor() as cur:
        cur.execute("select 1 from papel_plataforma limit 1")
        if cur.fetchone() is not None:
            raise PlataformaJaIniciadaError(
                "ja existe operador de plataforma; o primeiro so pode ser criado "
                "quando nao houver nenhum"
            )

        senha_hash, senha_params = hashear(senha)
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values (%s, %s, %s) returning id",
            (email, senha_hash, senha_params),
        )
        usuario_id = _um_valor(cur)
        cur.execute("insert into papel_plataforma (usuario_id) values (%s)", (usuario_id,))

    # Evento proprio: e o unico ato do sistema sem autor autenticado, e
    # registra-lo como concessao comum esconderia exatamente isso.
    registrar_plataforma(
        conexao,
        Principal.de_plataforma(usuario_id),
        "tenancy.plataforma_iniciada",
        f"usuario:{usuario_id}",
    )
    return UUID(str(usuario_id))


def _exigir_plataforma(principal: Principal, acao: Acao) -> None:
    if not pode(principal, acao):
        raise NaoEOperadorDePlataformaError(
            f"{acao.value} e acao de plataforma e este principal nao a tem"
        )


def criar_tenant(
    conexao: Conexao,
    quem: Principal,
    nome: str,
    identificador: str,
    primeiro_admin: UUID,
) -> UUID:
    """Cria o tenant **e** a primeira associacao, na mesma transacao."""
    _exigir_plataforma(quem, Acao.GERIR_TENANTS)

    with conexao.transaction(), conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values (%s, %s) returning id",
            (nome, identificador),
        )
        tenant_id = _um_valor(cur)

        # Contexto aberto no tenant que acabou de nascer, vazio.
        cur.execute("select set_config('vzdr.tenant_id', %s, true)", (str(tenant_id),))
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) values (%s, %s, 'admin')",
            (primeiro_admin, tenant_id),
        )

        # A linha que o cliente precisa ver: o provedor pos alguem aqui dentro.
        # O autor e o operador de plataforma, que nao e membro deste tenant —
        # por isso `auditoria.usuario_id` nao tem chave estrangeira.
        repositorio = Repositorio(
            conexao, Principal.de_usuario(quem.usuario_id, tenant_id, Papel.ADMIN)
        )
        with repositorio.transacao() as r:
            registrar(
                r,
                "tenancy.papel_concedido",
                f"usuario:{primeiro_admin}",
                {"papel": "admin", "por": "plataforma", "motivo": "criacao_do_tenant"},
            )

    registrar_plataforma(conexao, quem, "tenancy.tenant_criado", f"tenant:{tenant_id}")
    return UUID(str(tenant_id))


def autenticar_plataforma(conexao: Conexao, email: str, senha: str) -> str:
    """Sessao de plataforma. Token opaco inteiro: `sessao_plataforma` nao tem
    `tenant_id`, nao tem RLS, e portanto nao precisa do prefixo que a sessao de
    tenant precisa."""
    from vzdr.core.tenancy.autenticacao import CredenciaisInvalidasError
    from vzdr.core.tenancy.senha import verificar

    with conexao.transaction(), conexao.cursor() as cur:
        cur.execute(
            "select u.id, u.senha_hash, u.senha_params from usuarios u "
            "join papel_plataforma p on p.usuario_id = u.id "
            "where lower(u.email) = lower(%s)",
            (email,),
        )
        linha = cur.fetchone()
        if linha is None or not verificar(senha, linha[1], linha[2]):
            raise CredenciaisInvalidasError("e-mail ou senha invalidos")

        token = secrets.token_urlsafe(32)
        cur.execute(
            "insert into sessao_plataforma (token_hash, usuario_id, expira_em) values (%s, %s, %s)",
            (_hash_do_token(token), linha[0], datetime.now().astimezone() + DURACAO_DA_SESSAO),
        )
        return token


def verificar_plataforma(conexao: Conexao, token: str) -> Principal:
    """Resolve token de plataforma em `Principal` sem tenant."""
    from vzdr.core.tenancy.autenticacao import TokenExpiradoError, TokenInvalidoError

    with conexao.transaction(), conexao.cursor() as cur:
        cur.execute(
            "select usuario_id, expira_em <= now() from sessao_plataforma where token_hash = %s",
            (_hash_do_token(token),),
        )
        linha = cur.fetchone()

    if linha is None:
        raise TokenInvalidoError("desconhecida")
    usuario_id, expirada = linha
    if expirada:
        raise TokenExpiradoError("sessao expirada")
    return Principal.de_plataforma(usuario_id)


__all__ = [
    "NaoEOperadorDePlataformaError",
    "PlataformaJaIniciadaError",
    "autenticar_plataforma",
    "criar_tenant",
    "iniciar_plataforma",
    "verificar_plataforma",
]
