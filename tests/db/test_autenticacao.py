"""Autenticação, sessão e resolução de token.

Três testes aqui existem por causa de decisões específicas, não por completude:
o do re-hash, porque sem ele a migração preguiçosa nunca acontece; o do usuário
inexistente, porque o cronômetro enumera usuários; e o da contagem de consultas,
porque "uma consulta" foi requisito, não estimativa.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from vzdr.core.domain.tenancy import Origem, Papel
from vzdr.core.tenancy import autenticacao
from vzdr.core.tenancy.autenticacao import (
    CredenciaisInvalidasError,
    SemAssociacaoNoTenantError,
    TokenExpiradoError,
    TokenInvalidoError,
    VerificadorLocal,
    autenticar,
)
from vzdr.core.tenancy.senha import Politica, hashear

pytestmark = pytest.mark.db

SENHA = "senha-de-teste"
BARATA = Politica(ln=10, r=8, p=1)


@pytest.fixture()
def conta(conexao, esquema_migrado):  # noqa: ARG001 - precisa da migração aplicada
    """Um tenant, um usuário com senha e a associação entre eles."""
    h, p = hashear(SENHA, BARATA)
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values ('a', %s) returning id",
            (f"a-{uuid.uuid4().hex[:8]}",),
        )
        (tenant,) = cur.fetchone()
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) values (%s, %s, %s) "
            "returning id",
            (f"{uuid.uuid4().hex[:8]}@exemplo.test", h, p),
        )
        (usuario,) = cur.fetchone()
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) "
            "values (%s, %s, 'operator')",
            (usuario, tenant),
        )
        cur.execute("select email from usuarios where id = %s", (usuario,))
        (email,) = cur.fetchone()
    return tenant, usuario, email


def test_autentica_e_devolve_token(conexao, conta):
    tenant, _, email = conta
    token = autenticar(conexao, email, SENHA, tenant)
    assert token.startswith(f"{tenant}.")


def test_senha_errada_e_recusada(conexao, conta):
    tenant, _, email = conta
    with pytest.raises(CredenciaisInvalidasError):
        autenticar(conexao, email, "errada", tenant)


def test_email_ignora_caixa(conexao, conta):
    tenant, _, email = conta
    assert autenticar(conexao, email.upper(), SENHA, tenant)


def test_sem_associacao_no_tenant_e_recusado(conexao, conta):
    """Credencial certa, tenant errado. Erro distinto de senha errada."""
    _, _, email = conta
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values ('b', %s) returning id",
            (f"b-{uuid.uuid4().hex[:8]}",),
        )
        (outro,) = cur.fetchone()
    with pytest.raises(SemAssociacaoNoTenantError):
        autenticar(conexao, email, SENHA, outro)


def test_usuario_inexistente_gasta_o_mesmo_tempo(conexao, conta, monkeypatch):
    """Sem hash falso, o tempo de resposta enumera usuários.

    Contado, não cronometrado: medir relógio em teste é instável, e o que
    importa é que o caminho do inexistente **execute** o hash.
    """
    tenant, _, _ = conta
    chamadas = []
    original = autenticacao.verificar
    monkeypatch.setattr(
        autenticacao,
        "verificar",
        lambda *a, **k: (chamadas.append(1), original(*a, **k))[1],
    )
    with pytest.raises(CredenciaisInvalidasError):
        autenticar(conexao, "ninguem@exemplo.test", SENHA, tenant)
    assert len(chamadas) == 1


def test_usuario_inexistente_e_senha_errada_dao_o_mesmo_erro(conexao, conta):
    """Distinguir os dois entrega metade da credencial a quem perguntar."""
    tenant, _, email = conta
    with pytest.raises(CredenciaisInvalidasError) as a:
        autenticar(conexao, "ninguem@exemplo.test", SENHA, tenant)
    with pytest.raises(CredenciaisInvalidasError) as b:
        autenticar(conexao, email, "errada", tenant)
    assert str(a.value) == str(b.value)


# --------------------------------------------------------------------------
# Migração preguiçosa: sem isto, "é aditivo" é plano que nunca executa.
# --------------------------------------------------------------------------


def test_login_bem_sucedido_rehasheia_senha_defasada(conexao, conta):
    tenant, usuario, email = conta
    with conexao.cursor() as cur:
        cur.execute("select senha_params from usuarios where id = %s", (usuario,))
        (antes,) = cur.fetchone()
    assert antes.startswith("scrypt$ln=10,")

    autenticar(conexao, email, SENHA, tenant)

    with conexao.cursor() as cur:
        cur.execute("select senha_params from usuarios where id = %s", (usuario,))
        (depois,) = cur.fetchone()
    assert depois.startswith("scrypt$ln=16,r=8,p=2$")
    assert depois != antes


def test_a_senha_continua_valendo_depois_do_rehash(conexao, conta):
    tenant, _, email = conta
    autenticar(conexao, email, SENHA, tenant)
    assert autenticar(conexao, email, SENHA, tenant)


def test_senha_errada_nao_rehasheia(conexao, conta):
    tenant, usuario, email = conta
    with conexao.cursor() as cur:
        cur.execute("select senha_params from usuarios where id = %s", (usuario,))
        (antes,) = cur.fetchone()
    with pytest.raises(CredenciaisInvalidasError):
        autenticar(conexao, email, "errada", tenant)
    with conexao.cursor() as cur:
        cur.execute("select senha_params from usuarios where id = %s", (usuario,))
        assert cur.fetchone()[0] == antes


def test_senha_na_politica_nao_e_rehasheada(conexao, conta):
    """Re-hash só quando defasada — senão todo login paga o custo à toa."""
    tenant, usuario, email = conta
    autenticar(conexao, email, SENHA, tenant)
    with conexao.cursor() as cur:
        cur.execute("select senha_params from usuarios where id = %s", (usuario,))
        (primeiro,) = cur.fetchone()
    autenticar(conexao, email, SENHA, tenant)
    with conexao.cursor() as cur:
        cur.execute("select senha_params from usuarios where id = %s", (usuario,))
        assert cur.fetchone()[0] == primeiro


# --------------------------------------------------------------------------
# Resolução do token.
# --------------------------------------------------------------------------


def test_token_resolve_para_principal(conexao, conta):
    tenant, usuario, email = conta
    token = autenticar(conexao, email, SENHA, tenant)
    principal = VerificadorLocal(conexao).verificar(token)
    assert principal.usuario_id == usuario
    assert principal.tenant_id == tenant
    assert principal.papel is Papel.OPERATOR
    assert principal.origem is Origem.USUARIO


def test_o_papel_vem_da_associacao_e_nao_da_sessao(conexao, conta):
    """Rebaixar o dono vale já, não no próximo login."""
    tenant, usuario, email = conta
    token = autenticar(conexao, email, SENHA, tenant)
    with conexao.cursor() as cur:
        cur.execute(
            "update associacao_tenant set papel = 'viewer' "
            "where usuario_id = %s and tenant_id = %s",
            (usuario, tenant),
        )
    assert VerificadorLocal(conexao).verificar(token).papel is Papel.VIEWER


def test_revogar_o_papel_mata_a_sessao_viva(conexao, conta):
    """Não é só invalidar na próxima verificação: a linha some.

    Antes da migração 0004, tirar o papel de alguém matava o token de serviço
    na hora e deixava a sessão interativa valendo até expirar — até doze horas
    de acesso a um tenant de onde a pessoa foi removida. Não havia motivo para
    a diferença.
    """
    tenant, usuario, email = conta
    token = autenticar(conexao, email, SENHA, tenant)
    with conexao.cursor() as cur:
        cur.execute(
            "delete from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario, tenant),
        )
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (0,)
    with pytest.raises(TokenInvalidoError):
        VerificadorLocal(conexao).verificar(token)


def test_token_desconhecido_falha(conexao, conta):
    tenant, _, _ = conta
    with pytest.raises(TokenInvalidoError):
        VerificadorLocal(conexao).verificar(f"{tenant}.nao-existe")


@pytest.mark.parametrize("token", ["", "sem-ponto", "nao-e-uuid.segredo", "."])
def test_token_malformado_falha(conexao, conta, token):  # noqa: ARG001
    with pytest.raises(TokenInvalidoError):
        VerificadorLocal(conexao).verificar(token)


def test_malformado_e_desconhecido_respondem_igual(conexao, conta):
    """A diferença entre os dois não interessa a ninguém legítimo, e orienta
    quem está tentando: um diria "a estrutura estava errada", o outro "estava
    certa". O motivo fica em atributo, para o log."""
    tenant, _, _ = conta
    with pytest.raises(TokenInvalidoError) as malformado:
        VerificadorLocal(conexao).verificar("sem-ponto")
    with pytest.raises(TokenInvalidoError) as desconhecido:
        VerificadorLocal(conexao).verificar(f"{tenant}.nao-existe")

    assert str(malformado.value) == str(desconhecido.value)
    assert malformado.value.motivo != desconhecido.value.motivo


def test_token_expirado_falha_distinto_de_invalido(conexao, conta):
    """A interface diz coisas diferentes: 'entre de novo' e 'token errado'."""
    tenant, _, email = conta
    token = autenticar(conexao, email, SENHA, tenant)
    with conexao.cursor() as cur:
        cur.execute(
            "update sessao set expira_em = %s",
            (datetime.now(UTC) - timedelta(seconds=1),),
        )
    with pytest.raises(TokenExpiradoError):
        VerificadorLocal(conexao).verificar(token)


def test_trocar_o_prefixo_do_token_nao_abre_nada(conexao, conta):
    """O hash é do token inteiro: outro prefixo dá outro hash, e a RLS do
    tenant trocado esconderia a linha de qualquer jeito."""
    tenant, _, email = conta
    token = autenticar(conexao, email, SENHA, tenant)
    _, _, segredo = token.partition(".")
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values ('c', %s) returning id",
            (f"c-{uuid.uuid4().hex[:8]}",),
        )
        (outro,) = cur.fetchone()
    with pytest.raises(TokenInvalidoError):
        VerificadorLocal(conexao).verificar(f"{outro}.{segredo}")


def test_a_resolucao_usa_uma_consulta_so(conexao, conta, monkeypatch):
    """Requisito, não estimativa: sessão e papel na mesma consulta.

    São dois `execute`: o `set_config` que abre o contexto de tenant, e a
    resolução. O que o requisito proíbe é resolver o papel numa consulta
    separada da sessão.
    """
    tenant, _, email = conta
    token = autenticar(conexao, email, SENHA, tenant)

    executados = []
    original = type(conexao.cursor()).execute

    def contando(self, consulta, *args, **kwargs):
        executados.append(str(consulta))
        return original(self, consulta, *args, **kwargs)

    monkeypatch.setattr(type(conexao.cursor()), "execute", contando)
    VerificadorLocal(conexao).verificar(token)

    assert len(executados) == 2, executados
    assert "set_config" in executados[0]
    assert "from sessao" in executados[1]
    assert "associacao_tenant" in executados[1]
