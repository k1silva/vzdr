"""Papel de plataforma: o bootstrap sem autor e o tenant que nasce com admin."""

import uuid

import pytest

from vzdr.core.domain.tenancy import Acao, Papel, Principal, pode
from vzdr.core.tenancy.autenticacao import (
    CredenciaisInvalidasError,
    TokenInvalidoError,
)
from vzdr.core.tenancy.plataforma import (
    NaoEOperadorDePlataformaError,
    PlataformaJaIniciadaError,
    autenticar_plataforma,
    criar_tenant,
    iniciar_plataforma,
    verificar_plataforma,
)
from vzdr.core.tenancy.repositorio import PrincipalSemTenantError, Repositorio

pytestmark = pytest.mark.db

SENHA = "senha-do-operador"


@pytest.fixture()
def operador(conexao, esquema_migrado):  # noqa: ARG001 - precisa da migração aplicada
    return iniciar_plataforma(conexao, f"op-{uuid.uuid4().hex[:6]}@exemplo.test", SENHA)


def linhas(conexao, consulta, *args):
    with conexao.cursor() as cur:
        cur.execute(consulta, args)
        return cur.fetchall()


# --------------------------------------------------------------------------
# O bootstrap.
# --------------------------------------------------------------------------


def test_o_primeiro_operador_nasce_com_papel_de_plataforma(conexao, operador):
    assert linhas(conexao, "select usuario_id from papel_plataforma") == [(operador,)]


def test_o_bootstrap_e_auditado_como_evento_proprio(conexao, operador):  # noqa: ARG001
    """É o único ato sem autor autenticado; registrá-lo como concessão comum
    esconderia exatamente isso."""
    assert linhas(conexao, "select evento from auditoria_plataforma") == [
        ("tenancy.plataforma_iniciada",)
    ]


def test_o_bootstrap_recusa_se_ja_houver_operador(conexao, operador):  # noqa: ARG001
    with pytest.raises(PlataformaJaIniciadaError):
        iniciar_plataforma(conexao, "outro@exemplo.test", SENHA)


def test_a_condicao_e_sobre_o_estado_e_nao_sobre_o_historico(conexao, operador):
    """Perder todos os operadores não pode virar estado sem saída: ninguém
    existiria para autorizar a criação do primeiro de novo."""
    with conexao.cursor() as cur:
        cur.execute("delete from papel_plataforma where usuario_id = %s", (operador,))
    novo = iniciar_plataforma(conexao, f"n-{uuid.uuid4().hex[:6]}@exemplo.test", SENHA)
    assert novo != operador


def test_o_bootstrap_so_toca_tabelas_fora_do_eixo_de_tenant(conexao, operador):  # noqa: ARG001
    """Se precisasse de tabela com tenant_id, o desenho estaria errado: não
    existe tenant ainda."""
    for tabela in ("associacao_tenant", "sessao", "token_servico", "auditoria"):
        assert linhas(conexao, f"select count(*) from {tabela}")[0] == (0,)  # noqa: S608


def test_o_operador_autentica_e_o_token_resolve_sem_tenant(conexao, operador):
    principal = verificar_plataforma(
        conexao,
        autenticar_plataforma(conexao, linhas(conexao, "select email from usuarios")[0][0], SENHA),
    )
    assert principal.usuario_id == operador
    assert principal.plataforma is True
    assert principal.tenant_id is None


def test_senha_errada_nao_autentica_operador(conexao, operador):  # noqa: ARG001
    email = linhas(conexao, "select email from usuarios")[0][0]
    with pytest.raises(CredenciaisInvalidasError):
        autenticar_plataforma(conexao, email, "errada")


def test_quem_nao_e_operador_nao_autentica_como_plataforma(conexao, operador):  # noqa: ARG001
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values ('comum@exemplo.test','h','p')"
        )
    with pytest.raises(CredenciaisInvalidasError):
        autenticar_plataforma(conexao, "comum@exemplo.test", SENHA)


def test_token_de_plataforma_desconhecido_falha(conexao, operador):  # noqa: ARG001
    with pytest.raises(TokenInvalidoError):
        verificar_plataforma(conexao, "nao-existe")


# --------------------------------------------------------------------------
# criar_tenant: o tenant nunca nasce vazio.
# --------------------------------------------------------------------------


@pytest.fixture()
def admin(conexao, operador):  # noqa: ARG001
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values (%s,'h','p') returning id",
            (f"admin-{uuid.uuid4().hex[:6]}@exemplo.test",),
        )
        return cur.fetchone()[0]


def test_o_tenant_nasce_com_o_primeiro_admin(conexao, operador, admin):
    tenant = criar_tenant(
        conexao, Principal.de_plataforma(operador), "Cliente A", "cliente-a", admin
    )
    assert linhas(
        conexao,
        "select usuario_id, papel from associacao_tenant where tenant_id = %s",
        tenant,
    ) == [(admin, "admin")]


def test_tenant_vazio_nao_e_estado_do_sistema(conexao, operador, admin):
    """Não há instante em que o tenant exista sem associação: a mesma
    transação cria as duas coisas."""
    criar_tenant(conexao, Principal.de_plataforma(operador), "A", "a-1", admin)
    assert linhas(
        conexao,
        "select count(*) from tenants t where not exists "
        "(select 1 from associacao_tenant a where a.tenant_id = t.id)",
    ) == [(0,)]


def test_quem_nao_e_de_plataforma_nao_cria_tenant(conexao, operador, admin):  # noqa: ARG001
    comum = Principal.de_usuario(uuid.uuid4(), uuid.uuid4(), Papel.ADMIN)
    with pytest.raises(NaoEOperadorDePlataformaError):
        criar_tenant(conexao, comum, "A", "a-2", admin)


def test_identificador_repetido_falha(conexao, operador, admin):
    import psycopg

    quem = Principal.de_plataforma(operador)
    criar_tenant(conexao, quem, "A", "repetido", admin)
    with pytest.raises(psycopg.errors.UniqueViolation):
        criar_tenant(conexao, quem, "B", "repetido", admin)


# --------------------------------------------------------------------------
# A auditoria dupla: é a linha do cliente que importa.
# --------------------------------------------------------------------------


def test_a_criacao_e_auditada_nos_dois_lugares(conexao, operador, admin):
    tenant = criar_tenant(
        conexao, Principal.de_plataforma(operador), "Cliente A", "cliente-a", admin
    )

    assert ("tenancy.tenant_criado",) in linhas(conexao, "select evento from auditoria_plataforma")
    assert linhas(
        conexao,
        "select evento, usuario_id, detalhe ->> 'por' from auditoria where tenant_id = %s",
        tenant,
    ) == [("tenancy.papel_concedido", operador, "plataforma")]


def test_o_cliente_ve_quem_o_provedor_colocou_no_tenant_dele(conexao, operador, admin):
    """Sem esta linha, o provedor poderia pôr alguém no tenant de um cliente
    sem que o cliente conseguisse ver. Num produto vendido a terceiros, é *a*
    pergunta que a auditoria do cliente faz."""
    tenant = criar_tenant(
        conexao, Principal.de_plataforma(operador), "Cliente A", "cliente-a", admin
    )
    repo = Repositorio(conexao, Principal.de_usuario(admin, tenant, Papel.ADMIN))
    with repo.transacao() as r:
        vistos = r.selecionar("auditoria", ["evento", "autor", "alvo"])

    assert len(vistos) == 1
    evento, autor, alvo = vistos[0]
    assert evento == "tenancy.papel_concedido"
    assert alvo == f"usuario:{admin}"
    assert autor is not None and "@" in autor


# --------------------------------------------------------------------------
# A separação continua inteira.
# --------------------------------------------------------------------------


def test_o_operador_nao_abre_repositorio_de_tenant(conexao, operador, admin):
    """Criar tenant não deu a ele caminho geral de leitura."""
    criar_tenant(conexao, Principal.de_plataforma(operador), "A", "a-3", admin)
    with pytest.raises(PrincipalSemTenantError):
        Repositorio(conexao, Principal.de_plataforma(operador))


def test_o_operador_continua_negado_em_toda_acao_de_tenant(operador):
    principal = Principal.de_plataforma(operador)
    for acao in (Acao.LER, Acao.VER_SAUDE_TENANT, Acao.CONFIGURAR_PROTECAO):
        assert pode(principal, acao) is False
