"""A primeira migração, contra um Postgres de verdade.

O que se prova aqui é o que só o banco prova: que as colunas e as restrições
existem, e que o papel da aplicação tem exatamente os privilégios que deveria.
A RLS entra na migração seguinte.
"""

import uuid

import psycopg
import pytest

from tests.db.apoio import contexto_de_tenant

pytestmark = pytest.mark.db

# Da lista fechada de exceções em specs/core-001-tenancy/spec.md.
SEM_TENANT_ID = {
    "tenants",
    "usuarios",
    "papel_plataforma",
    "sessao_plataforma",
    "auditoria_plataforma",
    "schema_migrations",
}
COM_TENANT_ID = {
    "associacao_tenant",
    "sessao",
    "token_servico",
    "auditoria",
}


def colunas(conexao, esquema, tabela):
    with conexao.cursor() as cur:
        cur.execute(
            "select column_name, is_nullable from information_schema.columns "
            "where table_schema = %s and table_name = %s",
            (esquema, tabela),
        )
        return dict(cur.fetchall())


def semear(conexao):
    """Um tenant, um usuário e a associação entre eles."""
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values ('Cliente A', %s) returning id",
            (f"cliente-{uuid.uuid4().hex[:8]}",),
        )
        (tenant,) = cur.fetchone()
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values (%s, 'h', 'scrypt$ln=16,r=8,p=2$salt') returning id",
            (f"{uuid.uuid4().hex[:8]}@exemplo.test",),
        )
        (usuario,) = cur.fetchone()
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) values (%s, %s, 'admin')",
            (usuario, tenant),
        )
    return tenant, usuario


def test_migracao_aplica_e_o_checador_passa(esquema_migrado, conexao):
    with conexao.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables where table_schema = %s",
            (esquema_migrado,),
        )
        tabelas = {linha[0] for linha in cur.fetchall()}
    assert tabelas >= SEM_TENANT_ID | COM_TENANT_ID


@pytest.mark.parametrize("tabela", sorted(COM_TENANT_ID))
def test_tabela_de_dado_de_tenant_tem_tenant_id_nao_nulo(esquema_migrado, conexao, tabela):
    """P9. Nulável não serve: uma consulta filtrada descartaria a linha em silêncio."""
    assert colunas(conexao, esquema_migrado, tabela)["tenant_id"] == "NO"


@pytest.mark.parametrize("tabela", sorted(SEM_TENANT_ID - {"schema_migrations"}))
def test_tabela_isenta_nao_ganhou_tenant_id(esquema_migrado, conexao, tabela):
    assert "tenant_id" not in colunas(conexao, esquema_migrado, tabela)


@pytest.mark.usefixtures("esquema_migrado")
def test_papel_fora_do_vocabulario_e_recusado(conexao):
    """O banco não aceita papel que o domínio não conhece."""
    tenant, usuario = semear(conexao)
    with conexao.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) "
            "values (%s, %s, 'superusuario')",
            (usuario, tenant),
        )


@pytest.mark.usefixtures("esquema_migrado")
def test_email_e_unico_ignorando_caixa(conexao):
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values ('Kawan@Exemplo.test', 'h', 'p')"
        )
    with conexao.cursor() as cur, pytest.raises(psycopg.errors.UniqueViolation):
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values ('kawan@exemplo.test', 'h', 'p')"
        )


@pytest.mark.usefixtures("esquema_migrado")
def test_revogar_a_sessao_mae_revoga_a_filha(conexao):
    """Sessão irmã de troca de tenant não pode sobreviver à que a originou."""
    tenant, usuario = semear(conexao)
    with conexao.cursor() as cur:
        cur.execute(
            "insert into sessao (token_hash, usuario_id, tenant_id, expira_em) "
            "values ('mae', %s, %s, now() + interval '1 hour') returning id",
            (usuario, tenant),
        )
        (mae,) = cur.fetchone()
        cur.execute(
            "insert into sessao (token_hash, usuario_id, tenant_id, expira_em, sessao_pai_id) "
            "values ('filha', %s, %s, now() + interval '1 hour', %s)",
            (usuario, tenant, mae),
        )
        cur.execute("delete from sessao where id = %s", (mae,))
        cur.execute("select count(*) from sessao")
        assert cur.fetchone() == (0,)


@pytest.mark.usefixtures("esquema_migrado")
def test_perder_a_associacao_derruba_o_token_de_servico(conexao):
    """O token guarda o dono e o tenant, nunca o papel — e some com o vínculo."""
    tenant, usuario = semear(conexao)
    with conexao.cursor() as cur:
        cur.execute(
            "insert into token_servico (token_hash, usuario_dono_id, tenant_id, descricao) "
            "values ('t', %s, %s, 'cli')",
            (usuario, tenant),
        )
        cur.execute(
            "delete from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario, tenant),
        )
        cur.execute("select count(*) from token_servico")
        assert cur.fetchone() == (0,)


@pytest.mark.usefixtures("esquema_migrado")
def test_token_de_servico_sem_associacao_nao_nasce(conexao):
    tenant, _ = semear(conexao)
    with conexao.cursor() as cur, pytest.raises(psycopg.errors.ForeignKeyViolation):
        cur.execute(
            "insert into token_servico (token_hash, usuario_dono_id, tenant_id, descricao) "
            "values ('t2', %s, %s, 'cli')",
            (uuid.uuid4(), tenant),
        )


@pytest.mark.usefixtures("esquema_migrado")
def test_sessao_de_plataforma_exige_papel_de_plataforma(conexao):
    """Sessão de plataforma não é sessão de tenant sem tenant: é outra coisa."""
    _, usuario = semear(conexao)
    with conexao.cursor() as cur, pytest.raises(psycopg.errors.ForeignKeyViolation):
        cur.execute(
            "insert into sessao_plataforma (token_hash, usuario_id, expira_em) "
            "values ('sp', %s, now() + interval '1 hour')",
            (usuario,),
        )


@pytest.mark.usefixtures("esquema_migrado")
def test_aplicacao_escreve_e_le_nas_tabelas_de_tenant(conexao, conexao_app):
    semear(conexao)
    with conexao_app.cursor() as cur:
        cur.execute("select count(*) from tenants")
        assert cur.fetchone()[0] >= 1


@pytest.mark.usefixtures("esquema_migrado")
def test_aplicacao_insere_na_auditoria(conexao, conexao_app):
    tenant, usuario = semear(conexao)
    with contexto_de_tenant(conexao_app, tenant) as cur:
        cur.execute(
            "insert into auditoria (tenant_id, evento, usuario_id, alvo) "
            "values (%s, 'tenancy.papel_concedido', %s, 'usuario:x')",
            (tenant, usuario),
        )
        cur.execute("select count(*) from auditoria")
        assert cur.fetchone() == (1,)


@pytest.mark.usefixtures("esquema_migrado")
def test_aplicacao_nao_reescreve_a_auditoria(conexao, conexao_app):
    """Corrigir log é reescrever história. P8 depende de o registro ser o que
    aconteceu, não o que alguém preferiu depois."""
    tenant, usuario = semear(conexao)
    with contexto_de_tenant(conexao_app, tenant) as cur:
        cur.execute(
            "insert into auditoria (tenant_id, evento, usuario_id, alvo) "
            "values (%s, 'tenancy.papel_concedido', %s, 'usuario:x')",
            (tenant, usuario),
        )
    with conexao_app.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("update auditoria set evento = 'outro'")


@pytest.mark.usefixtures("esquema_migrado", "conexao")
def test_aplicacao_nao_apaga_a_auditoria(conexao_app):
    with conexao_app.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("delete from auditoria")


@pytest.mark.usefixtures("esquema_migrado", "conexao")
def test_aplicacao_nao_apaga_a_auditoria_de_plataforma(conexao_app):
    with conexao_app.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("delete from auditoria_plataforma")


@pytest.mark.usefixtures("esquema_migrado")
def test_aplicacao_nao_e_dona_das_tabelas(conexao_app):
    """Dono ignora política de RLS. Se a aplicação fosse dona, a migração
    seguinte passaria nos testes sem proteger nada (ADR-0006)."""
    with conexao_app.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("drop table auditoria")


def test_aplicacao_nao_e_superusuaria_nem_tem_bypassrls(conexao_app):
    """As duas coisas, nao uma. Superusuario ignora RLS sem ter a flag
    `rolbypassrls` ligada — checar so a flag deixaria o furo maior de fora."""
    with conexao_app.cursor() as cur:
        cur.execute("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
        assert cur.fetchone() == (False, False)
