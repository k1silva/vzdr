"""As duas camadas de isolamento, medidas SEPARADAMENTE.

A armadilha de ter repositório e RLS: um repositório que esqueça o filtro passa
em todos os testes, porque a RLS cobre o erro. Defesa em profundidade vira
detecção zero — ninguém descobre que esta camada quebrou até alguém consultar
por um caminho sem RLS.

Então aqui cada camada é medida sozinha:

- **o filtro do repositório**, pela conexão do dono, que é superusuária e ignora
  RLS. Se o filtro sumir, o teste reprova;
- **a RLS**, por consulta crua pela conexão da aplicação, sem repositório
  nenhum. Se a política sumir, o teste reprova.

O primeiro teste do arquivo prova a premissa: que o dono realmente ignora a RLS.
Sem ele, todos os outros poderiam estar medindo a política por engano.
"""

import uuid

import psycopg
import pytest

from vzdr.core.domain.tenancy import Papel, Principal
from vzdr.core.tenancy.repositorio import (
    PrincipalSemTenantError,
    Repositorio,
    TenantAlheioError,
)

pytestmark = pytest.mark.db


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
def cenario(conexao, esquema_migrado):  # noqa: ARG001 - precisa da migração aplicada
    """Dois tenants, com uma auditoria em cada. Semeado pelo dono."""
    a, b = criar_tenant(conexao, "a"), criar_tenant(conexao, "b")
    with conexao.cursor() as cur:
        for tenant in (a, b):
            usuario = criar_usuario(conexao)
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


def principal_de(tenant):
    return Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN)


# --------------------------------------------------------------------------
# A premissa: sem ela, os testes de filtro abaixo não provariam nada.
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("cenario")
def test_o_dono_ignora_a_rls(conexao):
    """Superusuário não é alcançado por FORCE ROW LEVEL SECURITY.

    É isto que torna a conexão do dono um banco de prova para o filtro do
    repositório: ali a RLS não está cobrindo erro nenhum.
    """
    with conexao.cursor() as cur:
        cur.execute("select count(distinct tenant_id) from auditoria")
        assert cur.fetchone() == (2,)


# --------------------------------------------------------------------------
# Camada 1, sozinha: o filtro do repositório, sem RLS em vigor.
# --------------------------------------------------------------------------


def test_o_filtro_do_repositorio_sozinho_isola(cenario, conexao):
    """Pela conexão do dono a RLS não vale. O que sobra é este filtro."""
    a, b = cenario
    repo = Repositorio(conexao, principal_de(a))
    linhas = repo.selecionar("auditoria", ["tenant_id"])
    assert {linha[0] for linha in linhas} == {a}
    assert b not in {linha[0] for linha in linhas}


def test_o_filtro_vale_tambem_no_outro_tenant(cenario, conexao):
    a, b = cenario
    repo = Repositorio(conexao, principal_de(b))
    assert {linha[0] for linha in repo.selecionar("auditoria", ["tenant_id"])} == {b}


def test_condicao_extra_nao_remove_o_filtro(cenario, conexao):
    """`onde` é acrescentado com `and`, nunca substitui o filtro de tenant."""
    a, _ = cenario
    repo = Repositorio(conexao, principal_de(a))
    linhas = repo.selecionar(
        "auditoria", ["tenant_id"], onde="evento = %s", parametros=("tenancy.papel_concedido",)
    )
    assert {linha[0] for linha in linhas} == {a}


def test_inserir_usa_o_tenant_do_principal(cenario, conexao):
    a, _ = cenario
    repo = Repositorio(conexao, principal_de(a))
    usuario = criar_usuario(conexao)
    repo.inserir("auditoria", {"evento": "teste", "usuario_id": usuario, "alvo": "x"})
    linhas = repo.selecionar("auditoria", ["tenant_id"], onde="evento = %s", parametros=("teste",))
    assert [linha[0] for linha in linhas] == [a]


def test_inserir_com_tenant_alheio_e_recusado_pelo_codigo(cenario, conexao):
    """Antes de a RLS opinar. O erro sai com o nome do problema."""
    a, b = cenario
    repo = Repositorio(conexao, principal_de(a))
    usuario = criar_usuario(conexao)
    with pytest.raises(TenantAlheioError) as erro:
        repo.inserir(
            "auditoria",
            {"tenant_id": b, "evento": "teste", "usuario_id": usuario, "alvo": "x"},
        )
    assert str(b) in str(erro.value)


def test_principal_de_plataforma_nao_abre_repositorio(conexao):
    """A segunda invariante da spec, em código: plataforma não lê dado de tenant."""
    with pytest.raises(PrincipalSemTenantError):
        Repositorio(conexao, Principal.de_plataforma(uuid.uuid4()))


# --------------------------------------------------------------------------
# Camada 2, sozinha: a RLS, sem repositório nenhum.
# --------------------------------------------------------------------------


def test_a_rls_sozinha_barra_consulta_sem_filtro(cenario, conexao_app):
    """Consulta crua, sem `where tenant_id` — é o repositório "quebrado"."""
    a, b = cenario
    with conexao_app.transaction(), conexao_app.cursor() as cur:
        cur.execute("select set_config('vzdr.tenant_id', %s, true)", (str(a),))
        cur.execute("select distinct tenant_id from auditoria")
        vistos = {linha[0] for linha in cur.fetchall()}
    assert vistos == {a}
    assert b not in vistos


@pytest.mark.usefixtures("cenario")
def test_a_rls_sozinha_devolve_vazio_sem_contexto(conexao_app):
    with conexao_app.cursor() as cur:
        cur.execute("select count(*) from auditoria")
        assert cur.fetchone() == (0,)


# --------------------------------------------------------------------------
# As duas juntas, como a aplicação vai usar.
# --------------------------------------------------------------------------


def test_transacao_amarra_o_contexto_e_o_solta(cenario, conexao_app):
    a, _ = cenario
    repo = Repositorio(conexao_app, principal_de(a))
    with repo.transacao() as r:
        assert len(r.selecionar("auditoria", ["id"])) == 1

    with conexao_app.cursor() as cur:
        cur.execute("select current_setting('vzdr.tenant_id', true)")
        assert cur.fetchone()[0] in (None, "")


def test_a_mesma_conexao_servindo_dois_tenants_nao_vaza(cenario, conexao_app):
    """O risco número um do plano, agora pela porta que a aplicação usa."""
    a, b = cenario
    for tenant in (a, b):
        repo = Repositorio(conexao_app, principal_de(tenant))
        with repo.transacao() as r:
            linhas = r.selecionar("auditoria", ["tenant_id"])
            assert {linha[0] for linha in linhas} == {tenant}


def test_escrever_no_tenant_alheio_pela_rls(cenario, conexao, conexao_app):
    """Se o código deixasse passar, a política barra. Simulado forçando a
    escrita crua com o contexto do outro tenant."""
    a, b = cenario
    usuario = criar_usuario(conexao)
    with conexao_app.transaction(), conexao_app.cursor() as cur:
        cur.execute("select set_config('vzdr.tenant_id', %s, true)", (str(a),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "insert into auditoria (tenant_id, evento, usuario_id, alvo) "
                "values (%s, 'x', %s, 'y')",
                (b, usuario),
            )
