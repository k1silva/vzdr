"""Isolamento entre tenants, provado contra o banco.

Tudo aqui fala pelo papel da aplicação. O dono do banco no laboratório é
superusuário e ignora RLS — testar por ele daria verde sem provar nada, que é
exatamente a armadilha que o ADR-0006 descreve.
"""

import uuid

import psycopg
import pytest

from tests.db.apoio import contexto_de_tenant

pytestmark = pytest.mark.db

# Espelha a migração 0002. Escrito à mão: derivar da migração faria o teste
# repetir a implementação.
COM_RLS = {"associacao_tenant", "sessao", "token_servico", "auditoria"}


def criar_tenant(conexao, nome):
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values (%s, %s) returning id",
            (nome, f"{nome}-{uuid.uuid4().hex[:8]}"),
        )
        return cur.fetchone()[0]


def criar_usuario(conexao):
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values (%s, 'h', 'p') returning id",
            (f"{uuid.uuid4().hex[:8]}@exemplo.test",),
        )
        return cur.fetchone()[0]


@pytest.fixture()
def dois_tenants(conexao, esquema_migrado):  # noqa: ARG001 - precisa da migração aplicada
    """Dois tenants, cada um com um usuário associado. Semeado pelo dono."""
    a, b = criar_tenant(conexao, "a"), criar_tenant(conexao, "b")
    ua, ub = criar_usuario(conexao), criar_usuario(conexao)
    with conexao.cursor() as cur:
        for tenant, usuario in ((a, ua), (b, ub)):
            cur.execute(
                "insert into associacao_tenant (usuario_id, tenant_id, papel) "
                "values (%s, %s, 'admin')",
                (usuario, tenant),
            )
            cur.execute(
                "insert into auditoria (tenant_id, evento, usuario_id, alvo) "
                "values (%s, 'tenancy.papel_concedido', %s, 'x')",
                (tenant, usuario),
            )
    return a, b


def test_toda_tabela_com_tenant_id_tem_rls_habilitada_e_forcada(conexao, esquema_migrado):
    """Varre o catálogo: tabela nova com tenant_id e sem política falha aqui."""
    with conexao.cursor() as cur:
        cur.execute(
            """
            select c.relname, c.relrowsecurity, c.relforcerowsecurity
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            join information_schema.columns col
              on col.table_schema = n.nspname
             and col.table_name = c.relname
             and col.column_name = 'tenant_id'
            where n.nspname = %s and c.relkind = 'r'
            """,
            (esquema_migrado,),
        )
        estado = {nome: (rls, forcada) for nome, rls, forcada in cur.fetchall()}

    assert set(estado) == COM_RLS
    for tabela, (rls, forcada) in sorted(estado.items()):
        assert rls, f"{tabela} tem tenant_id e está sem RLS"
        assert forcada, f"{tabela} tem RLS sem FORCE — o dono a ignora"


@pytest.mark.usefixtures("dois_tenants")
def test_sem_contexto_a_consulta_devolve_zero_linha(conexao_app):
    """Não é erro, é vazio — e é o bastante: o outro tenant não aparece."""
    with conexao_app.cursor() as cur:
        cur.execute("select count(*) from associacao_tenant")
        assert cur.fetchone() == (0,)
        cur.execute("select count(*) from auditoria")
        assert cur.fetchone() == (0,)


def test_com_contexto_enxerga_so_o_proprio_tenant(dois_tenants, conexao_app):
    a, b = dois_tenants
    for alvo, outro in ((a, b), (b, a)):
        with contexto_de_tenant(conexao_app, alvo) as cur:
            cur.execute("select tenant_id from associacao_tenant")
            vistos = {linha[0] for linha in cur.fetchall()}
            assert vistos == {alvo}
            assert outro not in vistos


def test_auditoria_de_um_tenant_nao_aparece_no_outro(dois_tenants, conexao_app):
    a, b = dois_tenants
    with contexto_de_tenant(conexao_app, a) as cur:
        cur.execute("select distinct tenant_id from auditoria")
        assert {linha[0] for linha in cur.fetchall()} == {a}


def test_escrever_no_tenant_alheio_e_recusado(dois_tenants, conexao, conexao_app):
    """A política barra a escrita, não só a leitura."""
    a, b = dois_tenants
    usuario = criar_usuario(conexao)
    with (
        contexto_de_tenant(conexao_app, a) as cur,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) "
            "values (%s, %s, 'viewer')",
            (usuario, b),
        )


def test_escrever_no_proprio_tenant_funciona(dois_tenants, conexao, conexao_app):
    a, _ = dois_tenants
    usuario = criar_usuario(conexao)
    with contexto_de_tenant(conexao_app, a) as cur:
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) "
            "values (%s, %s, 'viewer')",
            (usuario, a),
        )
        cur.execute("select count(*) from associacao_tenant")
        assert cur.fetchone() == (2,)


def test_a_mesma_conexao_servindo_dois_tenants_nao_vaza(dois_tenants, conexao_app):
    """O risco número um do plano: `SET` em vez de `SET LOCAL` gruda o tenant
    na conexão devolvida ao pool, e ela atende o próximo com o contexto errado.
    Este teste reusa deliberadamente a mesma conexão."""
    a, b = dois_tenants
    with contexto_de_tenant(conexao_app, a) as cur:
        cur.execute("select distinct tenant_id from associacao_tenant")
        assert {linha[0] for linha in cur.fetchall()} == {a}

    with contexto_de_tenant(conexao_app, b) as cur:
        cur.execute("select distinct tenant_id from associacao_tenant")
        assert {linha[0] for linha in cur.fetchall()} == {b}


def test_o_contexto_morre_com_a_transacao(dois_tenants, conexao_app):
    """Depois do commit, a conexão volta a não enxergar nada. É o que torna
    seguro devolvê-la ao pool."""
    a, _ = dois_tenants
    with contexto_de_tenant(conexao_app, a) as cur:
        cur.execute("select count(*) from associacao_tenant")
        assert cur.fetchone() == (1,)

    with conexao_app.cursor() as cur:
        cur.execute("select current_setting('vzdr.tenant_id', true)")
        assert cur.fetchone()[0] in (None, "")
        cur.execute("select count(*) from associacao_tenant")
        assert cur.fetchone() == (0,)


@pytest.mark.usefixtures("dois_tenants")
def test_contexto_de_tenant_inexistente_nao_enxerga_nada(conexao_app):
    """Adivinhar um uuid não abre porta nenhuma."""
    with contexto_de_tenant(conexao_app, uuid.uuid4()) as cur:
        cur.execute("select count(*) from associacao_tenant")
        assert cur.fetchone() == (0,)


@pytest.mark.usefixtures("dois_tenants")
def test_contexto_vazio_nao_quebra_a_consulta(conexao_app):
    """`nullif(..., '')`: string vazia vira NULL em vez de estourar o cast para
    uuid com uma mensagem que não se parece com o problema."""
    with conexao_app.transaction(), conexao_app.cursor() as cur:
        cur.execute("select set_config('vzdr.tenant_id', '', true)")
        cur.execute("select count(*) from associacao_tenant")
        assert cur.fetchone() == (0,)
