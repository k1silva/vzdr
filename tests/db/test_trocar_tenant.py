"""Trocar de tenant: a cadeia de sessões.

O que estes testes protegem não é a função — é que as três garantias sejam do
**banco** e não do código. Em especial a da expiração: ela tem que falhar
mesmo quando alguém escreve o `insert` à mão, errado.
"""

import uuid
from datetime import timedelta

import psycopg
import pytest

from vzdr.core.domain.tenancy import Papel
from vzdr.core.tenancy.autenticacao import (
    SemAssociacaoNoTenantError,
    TokenExpiradoError,
    TokenInvalidoError,
    VerificadorLocal,
    autenticar,
)
from vzdr.core.tenancy.senha import Politica, hashear
from vzdr.core.tenancy.sessao import TokenDeServicoNaoTrocaError, trocar_tenant

pytestmark = pytest.mark.db

SENHA = "senha-de-teste"
BARATA = Politica(ln=10, r=8, p=1)


@pytest.fixture()
def contas(conexao, esquema_migrado):  # noqa: ARG001 - precisa da migração aplicada
    """Um usuário com papel em três tenants: A (operator), B (admin), C (viewer)."""
    h, p = hashear(SENHA, BARATA)
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) values (%s,%s,%s) "
            "returning id, email",
            (f"{uuid.uuid4().hex[:8]}@exemplo.test", h, p),
        )
        usuario, email = cur.fetchone()
        tenants = {}
        for nome, papel in (("a", "operator"), ("b", "admin"), ("c", "viewer")):
            cur.execute(
                "insert into tenants (nome, identificador) values (%s,%s) returning id",
                (nome, f"{nome}-{uuid.uuid4().hex[:8]}"),
            )
            (tenants[nome],) = cur.fetchone()
            cur.execute(
                "insert into associacao_tenant (usuario_id, tenant_id, papel) values (%s,%s,%s)",
                (usuario, tenants[nome], papel),
            )
    return tenants, usuario, email


def expiracoes(conexao):
    with conexao.cursor() as cur:
        cur.execute("select expira_em from sessao")
        return {linha[0] for linha in cur.fetchall()}


def test_troca_devolve_token_do_destino(conexao, contas):
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    token_b = trocar_tenant(conexao, token_a, tenants["b"])
    assert token_b.startswith(f"{tenants['b']}.")
    assert token_b != token_a


def test_o_papel_vem_do_tenant_de_destino(conexao, contas):
    """Não é o papel de origem que viaja: é o de lá."""
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    assert VerificadorLocal(conexao).verificar(token_a).papel is Papel.OPERATOR

    token_b = trocar_tenant(conexao, token_a, tenants["b"])
    principal = VerificadorLocal(conexao).verificar(token_b)
    assert principal.papel is Papel.ADMIN
    assert principal.tenant_id == tenants["b"]


def test_a_sessao_de_origem_continua_valida(conexao, contas):
    """Trocar não é sair: quem trocou pode voltar."""
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    trocar_tenant(conexao, token_a, tenants["b"])
    assert VerificadorLocal(conexao).verificar(token_a).tenant_id == tenants["a"]


def test_sem_associacao_no_destino_e_recusado(conexao, contas):
    tenants, usuario, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    with conexao.cursor() as cur:
        cur.execute(
            "delete from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario, tenants["b"]),
        )
    with pytest.raises(SemAssociacaoNoTenantError):
        trocar_tenant(conexao, token_a, tenants["b"])


def test_trocar_para_o_mesmo_tenant_nao_cria_nivel(conexao, contas):
    """Devolver a mesma sessão seria mentir sobre ter criado uma, e criar um
    nível à toa engordaria a cadeia por nada."""
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    assert trocar_tenant(conexao, token_a, tenants["a"]) == token_a
    with conexao.cursor() as cur:
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (1,)


# --------------------------------------------------------------------------
# A garantia da expiração: é do banco, não do código.
# --------------------------------------------------------------------------


def test_a_filha_herda_a_expiracao_exata_da_mae(conexao, contas):
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    trocar_tenant(conexao, token_a, tenants["b"])
    assert len(expiracoes(conexao)) == 1


def test_troca_encadeada_nao_estende_o_relogio(conexao, contas):
    """A→B→C. Sem a garantia, cada salto renovaria a sessão."""
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    token_b = trocar_tenant(conexao, token_a, tenants["b"])
    trocar_tenant(conexao, token_b, tenants["c"])

    with conexao.cursor() as cur:
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (3,)
    assert len(expiracoes(conexao)) == 1


def test_o_banco_recusa_filha_com_expiracao_propria(conexao, contas):
    """O teste que importa: a garantia não depende de o código copiar certo.

    Escrito à mão, errado de propósito — é o que aconteceria se alguém
    escrevesse um segundo caminho de criação de sessão.
    """
    tenants, usuario, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    with conexao.cursor() as cur:
        cur.execute("select id, expira_em from sessao")
        mae, expira_em = cur.fetchone()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into sessao "
                "(token_hash, usuario_id, tenant_id, expira_em, sessao_pai_id) "
                "values ('x', %s, %s, %s, %s)",
                (usuario, tenants["b"], expira_em + timedelta(hours=8), mae),
            )
    assert token_a


# --------------------------------------------------------------------------
# A forma é cadeia: revogar um ancestral derruba tudo que desceu dele.
# --------------------------------------------------------------------------


def test_revogar_a_raiz_derruba_a_cadeia_inteira(conexao, contas):
    """Inclusive descendentes em outros tenants — a integridade referencial
    ignora RLS, e é isso que faz o cascade atravessar a fronteira."""
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    token_b = trocar_tenant(conexao, token_a, tenants["b"])
    trocar_tenant(conexao, token_b, tenants["c"])

    with conexao.cursor() as cur:
        cur.execute("delete from sessao where tenant_id = %s", (tenants["a"],))
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (0,)


def test_revogar_um_intermediario_derruba_so_o_que_desceu_dele(conexao, contas):
    """É a razão de a forma ser cadeia e não leque: C nasceu de B."""
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    token_b = trocar_tenant(conexao, token_a, tenants["b"])
    token_c = trocar_tenant(conexao, token_b, tenants["c"])

    with conexao.cursor() as cur:
        cur.execute("delete from sessao where tenant_id = %s", (tenants["b"],))

    assert VerificadorLocal(conexao).verificar(token_a).tenant_id == tenants["a"]
    for morto in (token_b, token_c):
        with pytest.raises(TokenInvalidoError):
            VerificadorLocal(conexao).verificar(morto)


def test_cadeia_profunda_cai_inteira(conexao, contas):
    """Alternar entre dois tenants não tem limite de profundidade, e o cascade
    do banco dá conta — nenhuma consulta daqui percorre a cadeia."""
    tenants, _, email = contas
    token = autenticar(conexao, email, SENHA, tenants["a"])
    for i in range(10):
        token = trocar_tenant(conexao, token, tenants["b" if i % 2 == 0 else "a"])

    with conexao.cursor() as cur:
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (11,)
        cur.execute("select id from sessao where sessao_pai_id is null")
        (raiz,) = cur.fetchone()
        cur.execute("delete from sessao where id = %s", (raiz,))
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (0,)


def test_revogar_o_papel_no_destino_mata_a_sessao_derivada(conexao, contas):
    """A raiz sobrevive: o papel revogado foi o de B, não o de A."""
    tenants, usuario, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    token_b = trocar_tenant(conexao, token_a, tenants["b"])

    with conexao.cursor() as cur:
        cur.execute(
            "delete from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario, tenants["b"]),
        )

    with pytest.raises(TokenInvalidoError):
        VerificadorLocal(conexao).verificar(token_b)
    assert VerificadorLocal(conexao).verificar(token_a).tenant_id == tenants["a"]


def test_revogar_o_papel_na_raiz_derruba_a_cadeia(conexao, contas):
    """O papel que sustenta a raiz sustenta tudo que desceu dela — inclusive
    sessões em tenants cujo papel continua valendo."""
    tenants, usuario, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    token_b = trocar_tenant(conexao, token_a, tenants["b"])

    with conexao.cursor() as cur:
        cur.execute(
            "delete from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario, tenants["a"]),
        )
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (0,)

    for morto in (token_a, token_b):
        with pytest.raises(TokenInvalidoError):
            VerificadorLocal(conexao).verificar(morto)


# --------------------------------------------------------------------------
# Recusas.
# --------------------------------------------------------------------------


def test_token_de_servico_nao_troca_de_tenant(conexao, contas):
    """A recusa é feita dentro de `trocar_tenant`, não por uma função que
    alguém precise lembrar de chamar antes."""
    import hashlib

    tenants, usuario, _ = contas
    token = f"{tenants['a']}.{uuid.uuid4().hex}"
    with conexao.cursor() as cur:
        cur.execute(
            "insert into token_servico (token_hash, usuario_dono_id, tenant_id, descricao) "
            "values (%s, %s, %s, 'cli')",
            (hashlib.sha256(token.encode()).hexdigest(), usuario, tenants["a"]),
        )
    with pytest.raises(TokenDeServicoNaoTrocaError):
        trocar_tenant(conexao, token, tenants["b"])


def test_token_desconhecido_e_recusado(conexao, contas):
    tenants, _, _ = contas
    with pytest.raises(TokenInvalidoError):
        trocar_tenant(conexao, f"{tenants['a']}.nao-existe", tenants["b"])


@pytest.mark.parametrize("token", ["", "sem-ponto", "nao-e-uuid.x", "."])
def test_token_malformado_e_recusado(conexao, contas, token):  # noqa: ARG001
    tenants, _, _ = contas
    with pytest.raises(TokenInvalidoError):
        trocar_tenant(conexao, token, tenants["b"])


def test_sessao_expirada_nao_troca(conexao, contas):
    tenants, _, email = contas
    token_a = autenticar(conexao, email, SENHA, tenants["a"])
    with conexao.cursor() as cur:
        cur.execute("update sessao set expira_em = now() - interval '1 second'")
    with pytest.raises(TokenExpiradoError):
        trocar_tenant(conexao, token_a, tenants["b"])
