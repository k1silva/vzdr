"""Conceder papel: uma regra de autorização, dois eventos."""

import uuid

import pytest

from vzdr.core.domain.tenancy import Papel, Principal
from vzdr.core.tenancy.papeis import (
    EVENTO_AUTOCONCEDIDO,
    EVENTO_CONCEDIDO,
    EVENTO_NEGADO,
    ConcessaoNegadaError,
    conceder_papel,
)
from vzdr.core.tenancy.plataforma import criar_tenant, iniciar_plataforma
from vzdr.core.tenancy.repositorio import PrincipalSemTenantError, Repositorio

pytestmark = pytest.mark.db


def criar_usuario(conexao):
    with conexao.cursor() as cur:
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values (%s,'h','p') returning id",
            (f"{uuid.uuid4().hex[:8]}@exemplo.test",),
        )
        return cur.fetchone()[0]


@pytest.fixture()
def tenant_com_admin(conexao, esquema_migrado):  # noqa: ARG001
    operador = iniciar_plataforma(conexao, "op@exemplo.test", "senha-do-operador")
    admin = criar_usuario(conexao)
    tenant = criar_tenant(
        conexao, Principal.de_plataforma(operador), "Cliente A", "cliente-a", admin
    )
    return tenant, admin


def auditoria(conexao, tenant, principal=None):
    repo = Repositorio(
        conexao, principal or Principal.de_usuario(uuid.uuid4(), tenant, Papel.ADMIN)
    )
    with repo.transacao() as r:
        return r.selecionar("auditoria", ["evento", "alvo", "detalhe"])


def papel_de(conexao, usuario, tenant):
    with conexao.cursor() as cur:
        cur.execute(
            "select papel from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (usuario, tenant),
        )
        linha = cur.fetchone()
        return linha[0] if linha else None


def test_admin_concede_papel_a_outro(conexao, tenant_com_admin):
    tenant, admin = tenant_com_admin
    novo = criar_usuario(conexao)
    conceder_papel(conexao, Principal.de_usuario(admin, tenant, Papel.ADMIN), novo, Papel.OPERATOR)
    assert papel_de(conexao, novo, tenant) == "operator"


def test_conceder_a_outro_emite_papel_concedido(conexao, tenant_com_admin):
    tenant, admin = tenant_com_admin
    novo = criar_usuario(conexao)
    conceder_papel(conexao, Principal.de_usuario(admin, tenant, Papel.ADMIN), novo, Papel.VIEWER)
    eventos = [linha[0] for linha in auditoria(conexao, tenant)]
    assert eventos.count(EVENTO_CONCEDIDO) == 2  # a da criação + esta
    assert EVENTO_AUTOCONCEDIDO not in eventos


def test_conceder_a_si_mesmo_emite_o_outro_evento_e_nunca_os_dois(conexao, tenant_com_admin):
    """Auto-concessão com tipo próprio é o que permite alertar sobre ela."""
    tenant, admin = tenant_com_admin
    conceder_papel(conexao, Principal.de_usuario(admin, tenant, Papel.ADMIN), admin, Papel.ADMIN)
    eventos = [linha[0] for linha in auditoria(conexao, tenant)]
    assert eventos.count(EVENTO_AUTOCONCEDIDO) == 1
    assert eventos.count(EVENTO_CONCEDIDO) == 1  # só a da criação do tenant


def test_a_autoconcessao_e_consultavel_sem_varrer_o_log(conexao, tenant_com_admin):
    """Ter tipo próprio é o que permite alertar sem ler o resto."""
    tenant, admin = tenant_com_admin
    quem = Principal.de_usuario(admin, tenant, Papel.ADMIN)
    for _ in range(5):
        conceder_papel(conexao, quem, criar_usuario(conexao), Papel.VIEWER)
    conceder_papel(conexao, quem, admin, Papel.ADMIN)

    repo = Repositorio(conexao, quem)
    with repo.transacao() as r:
        achadas = r.selecionar(
            "auditoria", ["alvo"], onde="evento = %s", parametros=(EVENTO_AUTOCONCEDIDO,)
        )
    assert achadas == [(f"usuario:{admin}",)]


def test_alterar_papel_registra_o_anterior(conexao, tenant_com_admin):
    """Quem investiga precisa saber de onde a pessoa veio, não só onde está."""
    tenant, admin = tenant_com_admin
    quem = Principal.de_usuario(admin, tenant, Papel.ADMIN)
    outro = criar_usuario(conexao)
    conceder_papel(conexao, quem, outro, Papel.VIEWER)
    conceder_papel(conexao, quem, outro, Papel.ADMIN)

    assert papel_de(conexao, outro, tenant) == "admin"
    detalhes = [linha[2] for linha in auditoria(conexao, tenant) if linha[2]]
    assert {"papel": "admin", "papel_anterior": "viewer"} in detalhes


def test_quem_virou_admin_e_veio_de_onde_sai_de_uma_tabela_so(conexao, tenant_com_admin):
    """A operação é uma; o histórico tem dois casos. `papel_anterior` nulo ou
    não distingue promoção de concessão inicial — sem juntar tabelas."""
    tenant, admin = tenant_com_admin
    quem = Principal.de_usuario(admin, tenant, Papel.ADMIN)
    promovido, direto = criar_usuario(conexao), criar_usuario(conexao)
    conceder_papel(conexao, quem, promovido, Papel.VIEWER)
    conceder_papel(conexao, quem, promovido, Papel.ADMIN)
    conceder_papel(conexao, quem, direto, Papel.ADMIN)

    repo = Repositorio(conexao, quem)
    with repo.transacao() as r:
        virou_admin = r.selecionar(
            "auditoria",
            ["alvo", "detalhe", "autor", "ocorrido_em"],
            onde="detalhe ->> 'papel' = %s",
            parametros=("admin",),
        )

    de_onde = {alvo: d.get("papel_anterior") for alvo, d, _, _ in virou_admin}
    assert de_onde[f"usuario:{promovido}"] == "viewer"
    assert de_onde[f"usuario:{direto}"] is None


# --------------------------------------------------------------------------
# Uma regra de autorização, não duas.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("papel", [Papel.VIEWER, Papel.OPERATOR])
def test_quem_nao_e_admin_nao_concede(conexao, tenant_com_admin, papel):
    tenant, admin = tenant_com_admin
    fraco = criar_usuario(conexao)
    conceder_papel(conexao, Principal.de_usuario(admin, tenant, Papel.ADMIN), fraco, papel)

    with pytest.raises(ConcessaoNegadaError):
        conceder_papel(
            conexao,
            Principal.de_usuario(fraco, tenant, papel),
            criar_usuario(conexao),
            Papel.ADMIN,
        )


def test_a_tentativa_negada_aparece_na_auditoria(conexao, tenant_com_admin):
    tenant, admin = tenant_com_admin
    fraco = criar_usuario(conexao)
    conceder_papel(conexao, Principal.de_usuario(admin, tenant, Papel.ADMIN), fraco, Papel.VIEWER)
    alvo = criar_usuario(conexao)
    with pytest.raises(ConcessaoNegadaError):
        conceder_papel(
            conexao, Principal.de_usuario(fraco, tenant, Papel.VIEWER), alvo, Papel.ADMIN
        )

    negadas = [linha for linha in auditoria(conexao, tenant) if linha[0] == EVENTO_NEGADO]
    assert len(negadas) == 1
    assert negadas[0][1] == f"usuario:{alvo}"
    assert negadas[0][2]["papel_de_quem_pediu"] == "viewer"


def test_a_tentativa_negada_nao_altera_nada(conexao, tenant_com_admin):
    tenant, admin = tenant_com_admin
    fraco = criar_usuario(conexao)
    conceder_papel(conexao, Principal.de_usuario(admin, tenant, Papel.ADMIN), fraco, Papel.VIEWER)
    alvo = criar_usuario(conexao)
    with pytest.raises(ConcessaoNegadaError):
        conceder_papel(
            conexao, Principal.de_usuario(fraco, tenant, Papel.VIEWER), alvo, Papel.ADMIN
        )
    assert papel_de(conexao, alvo, tenant) is None


def test_operador_de_plataforma_nao_concede_por_aqui(conexao, tenant_com_admin):
    """A segunda regra de autorização não existe: conceder o primeiro papel é
    parte de `criar_tenant`, operação diferente."""
    _, _ = tenant_com_admin
    with pytest.raises(PrincipalSemTenantError):
        conceder_papel(conexao, Principal.de_plataforma(uuid.uuid4()), uuid.uuid4(), Papel.ADMIN)
