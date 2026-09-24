"""Auditoria: a tabela certa, e o humano por trás do token.

Duas tabelas, duas funções. A separação é o que impede um ato de plataforma de
aparecer como se tivesse acontecido dentro de um tenant.
"""

import uuid

import pytest

from vzdr.core.audit import (
    PrincipalNaoEDePlataformaError,
    registrar,
    registrar_plataforma,
)
from vzdr.core.domain.tenancy import Papel, Principal
from vzdr.core.tenancy.repositorio import Repositorio

pytestmark = pytest.mark.db


@pytest.fixture()
def tenant(conexao, esquema_migrado):  # noqa: ARG001 - precisa da migração aplicada
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values ('a', %s) returning id",
            (f"a-{uuid.uuid4().hex[:8]}",),
        )
        return cur.fetchone()[0]


def contar(conexao, tabela):
    with conexao.cursor() as cur:
        cur.execute(f"select count(*) from {tabela}")  # noqa: S608 - nome fixo no teste
        return cur.fetchone()[0]


def test_ato_de_tenant_vai_para_auditoria_e_nao_para_a_de_plataforma(conexao, tenant):
    repo = Repositorio(conexao, Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN))
    with repo.transacao() as r:
        registrar(r, "tenancy.papel_concedido", "usuario:x")
    assert contar(conexao, "auditoria") == 1
    assert contar(conexao, "auditoria_plataforma") == 0


def test_ato_de_plataforma_vai_para_a_outra_tabela(conexao, tenant):  # noqa: ARG001
    registrar_plataforma(
        conexao, Principal.de_plataforma(uuid.uuid4()), "tenancy.tenant_criado", "tenant:a"
    )
    assert contar(conexao, "auditoria_plataforma") == 1
    assert contar(conexao, "auditoria") == 0


def test_o_tenant_da_linha_vem_do_principal(conexao, tenant):
    repo = Repositorio(conexao, Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN))
    with repo.transacao() as r:
        registrar(r, "tenancy.papel_concedido", "usuario:x")
        linhas = r.selecionar("auditoria", ["tenant_id"])
    assert [linha[0] for linha in linhas] == [tenant]


def test_acao_por_token_de_servico_grava_servico_e_dono(conexao, tenant):
    """P6 e P8: registrar só o serviço apaga de quem a autoridade foi
    emprestada. É a pergunta que alguém faz quando um assistente de IA agiu."""
    dono, servico = uuid.uuid4(), uuid.uuid4()
    repo = Repositorio(conexao, Principal.de_servico(dono, servico, tenant, Papel.ADMIN))
    with repo.transacao() as r:
        registrar(r, "dr.ciclo_concluido", "vm:jau-server01")
        linhas = r.selecionar("auditoria", ["usuario_id", "servico_id"])
    assert linhas == [(dono, servico)]


def test_acao_por_usuario_nao_inventa_servico(conexao, tenant):
    usuario = uuid.uuid4()
    repo = Repositorio(conexao, Principal.de_usuario(usuario, tenant, Papel.ADMIN))
    with repo.transacao() as r:
        registrar(r, "dr.ciclo_concluido", "vm:x")
        assert r.selecionar("auditoria", ["usuario_id", "servico_id"]) == [(usuario, None)]


def test_principal_de_tenant_nao_registra_ato_de_plataforma(conexao, tenant):
    """Deixar passar desfaria a separação que as duas tabelas mantêm."""
    principal = Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN)
    with pytest.raises(PrincipalNaoEDePlataformaError) as erro:
        registrar_plataforma(conexao, principal, "tenancy.tenant_criado", "tenant:b")
    assert "registrar()" in str(erro.value)
    assert contar(conexao, "auditoria_plataforma") == 0


def test_o_autor_fica_legivel_depois_de_o_usuario_sumir(conexao, tenant):
    """Auditoria não é autorização: o registro tem que sobreviver à remoção do
    que referencia — e sobreviver não basta, precisa continuar legível.

    Revogar alguém não pode apagar a prova do que essa pessoa fez, e um uuid
    que não aponta para lugar nenhum não responde "quem fez".
    """
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values ('quem.agiu@exemplo.test','h','p') returning id"
        )
        (usuario,) = cur.fetchone()
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) values (%s, %s, 'admin')",
            (usuario, tenant),
        )

    repo = Repositorio(conexao, Principal.de_usuario(usuario, tenant, Papel.ADMIN))
    with repo.transacao() as r:
        registrar(r, "tenancy.papel_concedido", "usuario:x")

    with conexao.cursor() as cur:
        cur.execute("delete from usuarios where id = %s", (usuario,))
        cur.execute("select usuario_id, autor from auditoria")
        gravado, autor = cur.fetchone()

    assert gravado == usuario
    assert autor == "quem.agiu@exemplo.test"


def test_o_autor_de_ato_de_plataforma_tambem_e_legivel(conexao, tenant):  # noqa: ARG001
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values ('operador@exemplo.test','h','p') returning id"
        )
        (usuario,) = cur.fetchone()

    registrar_plataforma(
        conexao, Principal.de_plataforma(usuario), "tenancy.tenant_criado", "tenant:x"
    )
    with conexao.cursor() as cur:
        cur.execute("select autor from auditoria_plataforma")
        assert cur.fetchone() == ("operador@exemplo.test",)


def test_detalhe_vira_jsonb_consultavel(conexao, tenant):
    repo = Repositorio(conexao, Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN))
    with repo.transacao() as r:
        registrar(r, "tenancy.papel_autoconcedido", "usuario:x", {"papel": "admin"})
        linhas = r.selecionar(
            "auditoria", ["evento"], onde="detalhe ->> 'papel' = %s", parametros=("admin",)
        )
    assert [linha[0] for linha in linhas] == ["tenancy.papel_autoconcedido"]


def test_sem_detalhe_a_coluna_fica_nula(conexao, tenant):
    repo = Repositorio(conexao, Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN))
    with repo.transacao() as r:
        registrar(r, "dr.ciclo_concluido", "vm:x")
        assert r.selecionar("auditoria", ["detalhe"]) == [(None,)]


def test_a_aplicacao_registra_e_nao_reescreve(conexao, conexao_app, tenant):
    """Append-only na prática, pela conexão que a aplicação usa."""
    import psycopg

    principal = Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN)
    repo = Repositorio(conexao_app, principal)
    with repo.transacao() as r:
        registrar(r, "tenancy.papel_concedido", "usuario:x")

    with conexao_app.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("update auditoria set evento = 'outro'")
    assert contar(conexao, "auditoria") == 1
