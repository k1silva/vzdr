"""Autenticar, emitir sessao, e resolver token em `Principal`.

## O token carrega o tenant em claro, e por que

O token e `<tenant_id>.<segredo>`. O segredo e aleatorio
(`secrets.token_urlsafe(32)`) e o banco guarda so o SHA-256 do token inteiro.

O prefixo existe por um motivo que a spec nao previu: `sessao` tem `tenant_id`
e portanto tem RLS, e ler a linha exige o contexto de tenant — que so se sabe
LENDO a linha. Sem o prefixo, resolver um token seria um ovo-e-galinha, e as
saidas seriam piores: dar ao verificador uma conexao sem RLS, tirar a RLS de
`sessao`, ou criar uma funcao `security definer` que a contorna. Todas trocam
um problema de bootstrap por uma superficie privilegiada nova.

Trocar o prefixo por outro tenant nao abre nada: o hash guardado e do token
inteiro, entao um prefixo diferente da um hash diferente, e a linha some de
qualquer jeito pela propria RLS. E o que o prefixo revela — o tenant de quem ja
tem o token — e coisa que o portador ja sabe.

Sessao de plataforma nao tem este problema: `sessao_plataforma` nao tem
`tenant_id`, nao tem RLS, e o token dela e opaco inteiro.

## O papel nunca vem da sessao

A consulta de resolucao junta `sessao` com `associacao_tenant`. E de la que o
papel sai, sempre. Congelar o papel na sessao faria um rebaixamento so valer no
proximo login — exatamente o que a spec recusa para token de servico.

## Usuario inexistente gasta o mesmo tempo

Sem isso, o tempo de resposta enumera usuarios: "esse e-mail existe" vaza por
um cronometro. O caminho do usuario inexistente roda um scrypt contra um hash
descartavel, com os mesmos parametros da politica.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from psycopg import sql

from vzdr.core.domain.tenancy import Papel, Principal
from vzdr.core.tenancy.senha import POLITICA, hashear, precisa_de_rehash, verificar

if TYPE_CHECKING:
    import psycopg

    Conexao = psycopg.Connection[Any]

VARIAVEL_DE_CONTEXTO = "vzdr.tenant_id"
DURACAO_DA_SESSAO = timedelta(hours=12)

#: Hash descartavel, gerado uma vez por processo, para o caminho do usuario
#: inexistente gastar o mesmo tempo do caminho normal.
_FALSO_HASH, _FALSO_PARAMS = hashear(secrets.token_urlsafe(32), POLITICA)


class CredenciaisInvalidasError(Exception):
    """E-mail ou senha errados.

    Uma excecao so para os dois de proposito: distinguir "usuario nao existe" de
    "senha errada" entrega metade da credencial a quem perguntar.
    """


class SemAssociacaoNoTenantError(Exception):
    """Usuario existe e a senha confere, mas ele nao tem papel neste tenant."""


class TokenInvalidoError(Exception):
    """Token malformado, desconhecido, ou cuja sessao nao existe mais.

    A mensagem e a MESMA nos tres casos. "Token malformado" contaria a quem
    tenta que a estrutura estava errada, e "sessao desconhecida" contaria que
    estava certa — diferenca que nao interessa a ninguem legitimo e orienta
    quem esta tentando.

    O `motivo` fica em atributo, para log e auditoria, e nao na mensagem: assim
    a distincao serve ao diagnostico (P8) sem depender de alguem lembrar de
    nao devolve-la na resposta.
    """

    MENSAGEM = "token invalido"

    def __init__(self, motivo: str) -> None:
        super().__init__(self.MENSAGEM)
        self.motivo = motivo


class TokenExpiradoError(Exception):
    """Sessao existiu e venceu. Distinto de invalido: muda o que a interface diz."""


def _hash_do_token(token: str) -> str:
    # Token e aleatorio de alta entropia: nao ha o que adivinhar, entao SHA-256
    # e nao um KDF lento. Senha e outra coisa — ver senha.py.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _abrir_contexto(cur: Any, tenant_id: UUID | str) -> None:
    cur.execute("select set_config(%s, %s, true)", (VARIAVEL_DE_CONTEXTO, str(tenant_id)))


def autenticar(conexao: Conexao, email: str, senha: str, tenant_id: UUID) -> str:
    """Devolve o token da sessao, ou levanta.

    Re-hasheia a senha quando a linha esta defasada em relacao a politica. E
    aqui, e so aqui, porque este e o unico momento em que a senha em claro
    existe — sem isto, "adotar Argon2id depois e aditivo" seria plano que nunca
    executa.
    """
    with conexao.transaction(), conexao.cursor() as cur:
        _abrir_contexto(cur, tenant_id)

        cur.execute(
            "select id, senha_hash, senha_params from usuarios where lower(email) = lower(%s)",
            (email,),
        )
        linha = cur.fetchone()

        if linha is None:
            # Gasta o mesmo tempo. Sem isto o cronometro enumera usuarios.
            verificar(senha, _FALSO_HASH, _FALSO_PARAMS)
            raise CredenciaisInvalidasError("e-mail ou senha invalidos")

        usuario_id, senha_hash, senha_params = linha
        if not verificar(senha, senha_hash, senha_params):
            raise CredenciaisInvalidasError("e-mail ou senha invalidos")

        if precisa_de_rehash(senha_params):
            novo_hash, novos_params = hashear(senha)
            cur.execute(
                "update usuarios set senha_hash = %s, senha_params = %s where id = %s",
                (novo_hash, novos_params, usuario_id),
            )

        cur.execute(
            "select papel from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario_id, tenant_id),
        )
        if cur.fetchone() is None:
            raise SemAssociacaoNoTenantError(f"usuario nao tem papel no tenant {tenant_id}")

        token = f"{tenant_id}.{secrets.token_urlsafe(32)}"
        cur.execute(
            "insert into sessao (token_hash, usuario_id, tenant_id, expira_em) "
            "values (%s, %s, %s, %s)",
            (
                _hash_do_token(token),
                usuario_id,
                tenant_id,
                datetime.now(UTC) + DURACAO_DA_SESSAO,
            ),
        )
        return token


class VerificadorDeToken(Protocol):
    """A fronteira que a spec prometeu.

    Um validador OIDC entra como segundo implementador, sem tocar em quem
    consome `Principal`.
    """

    def verificar(self, token: str) -> Principal: ...


#: Sessao e papel numa consulta so.
#:
#: `join` e nao `left join`: desde a migracao 0004 a sessao nao sobrevive a
#: perda da associacao — a chave composta a apaga em cascata. Um `left join`
#: aqui trataria um caso que o esquema tornou impossivel, e ramo que nenhum
#: teste consegue exercitar e pior que ramo ausente.
_RESOLVER = sql.SQL(
    "select s.usuario_id, s.tenant_id, s.expira_em, a.papel "
    "from sessao s "
    "join associacao_tenant a "
    "  on a.usuario_id = s.usuario_id and a.tenant_id = s.tenant_id "
    "where s.token_hash = %s"
)


class VerificadorLocal:
    """Unico implementador hoje: sessao emitida por esta plataforma."""

    def __init__(self, conexao: Conexao) -> None:
        self._conexao = conexao

    def verificar(self, token: str) -> Principal:
        tenant, _, segredo = token.partition(".")
        if not segredo:
            raise TokenInvalidoError("token malformado")
        try:
            tenant_id = UUID(tenant)
        except ValueError as erro:
            raise TokenInvalidoError("token malformado") from erro

        with self._conexao.transaction(), self._conexao.cursor() as cur:
            _abrir_contexto(cur, tenant_id)
            cur.execute(_RESOLVER, (_hash_do_token(token),))
            linha = cur.fetchone()

        if linha is None:
            # Pode ser token de servico: mesmo formato, outra tabela. Quem
            # recebe um token nao sabe de que tipo ele e, e fazer a API
            # escolher seria mais uma coisa para alguem lembrar.
            #
            # LIMITE DESTA CADEIA: ela custa uma consulta a mais no caminho de
            # falha, o que com dois tipos e irrelevante. Se aparecer um
            # TERCEIRO, a saida NAO e encadear mais um `if` — e discriminar o
            # tipo no proprio token, como o prefixo ja faz com o tenant. Sem
            # esta nota, o terceiro tipo vira mais um elif e o quarto tambem.
            #
            # Import tardio porque `servico` depende deste modulo: a direcao da
            # dependencia e servico -> autenticacao, e so este ponto a inverte.
            from vzdr.core.tenancy.servico import resolver as resolver_servico

            return resolver_servico(self._conexao, token)

        usuario_id, tenant_da_linha, expira_em, papel = linha
        if expira_em <= datetime.now(UTC):
            raise TokenExpiradoError("sessao expirada")

        return Principal.de_usuario(usuario_id, tenant_da_linha, Papel(papel))
