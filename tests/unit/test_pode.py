"""A matriz de permissao, inteira, concedida e negada.

A matriz esperada esta escrita a mao de proposito. Deriva-la de `_PERMISSOES`
faria o teste repetir a implementacao e passar com ela errada.
"""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from vzdr.core.domain.tenancy import (
    ACOES_DE_PLATAFORMA,
    ACOES_DE_TENANT,
    Acao,
    Origem,
    Papel,
    Principal,
    PrincipalInvalidoError,
    e_destrutiva,
    pode,
)

PLATAFORMA = "plataforma"

# (quem, acao) -> pode?
MATRIZ = {
    (Papel.VIEWER, Acao.LER): True,
    (Papel.VIEWER, Acao.CONFIGURAR_PROTECAO): False,
    (Papel.VIEWER, Acao.RODAR_TEST_FAILOVER): False,
    (Papel.VIEWER, Acao.DISPARAR_FAILOVER): False,
    (Papel.VIEWER, Acao.GERIR_USUARIOS): False,
    (Papel.VIEWER, Acao.VER_SAUDE_TENANT): True,
    (Papel.VIEWER, Acao.GERIR_TENANTS): False,
    (Papel.VIEWER, Acao.VER_SAUDE_PLATAFORMA): False,
    (Papel.OPERATOR, Acao.LER): True,
    (Papel.OPERATOR, Acao.CONFIGURAR_PROTECAO): True,
    (Papel.OPERATOR, Acao.RODAR_TEST_FAILOVER): True,
    (Papel.OPERATOR, Acao.DISPARAR_FAILOVER): False,
    (Papel.OPERATOR, Acao.GERIR_USUARIOS): False,
    (Papel.OPERATOR, Acao.VER_SAUDE_TENANT): True,
    (Papel.OPERATOR, Acao.GERIR_TENANTS): False,
    (Papel.OPERATOR, Acao.VER_SAUDE_PLATAFORMA): False,
    (Papel.ADMIN, Acao.LER): True,
    (Papel.ADMIN, Acao.CONFIGURAR_PROTECAO): True,
    (Papel.ADMIN, Acao.RODAR_TEST_FAILOVER): True,
    (Papel.ADMIN, Acao.DISPARAR_FAILOVER): True,
    (Papel.ADMIN, Acao.GERIR_USUARIOS): True,
    (Papel.ADMIN, Acao.VER_SAUDE_TENANT): True,
    (Papel.ADMIN, Acao.GERIR_TENANTS): False,
    (Papel.ADMIN, Acao.VER_SAUDE_PLATAFORMA): False,
    (PLATAFORMA, Acao.LER): False,
    (PLATAFORMA, Acao.CONFIGURAR_PROTECAO): False,
    (PLATAFORMA, Acao.RODAR_TEST_FAILOVER): False,
    (PLATAFORMA, Acao.DISPARAR_FAILOVER): False,
    (PLATAFORMA, Acao.GERIR_USUARIOS): False,
    (PLATAFORMA, Acao.VER_SAUDE_TENANT): False,
    (PLATAFORMA, Acao.GERIR_TENANTS): True,
    (PLATAFORMA, Acao.VER_SAUDE_PLATAFORMA): True,
}


def principal_de(quem):
    if quem is PLATAFORMA:
        return Principal.de_plataforma(uuid4())
    return Principal.de_usuario(uuid4(), uuid4(), quem)


@pytest.mark.parametrize(("quem", "acao"), sorted(MATRIZ, key=repr))
def test_matriz_de_permissao(quem, acao):
    assert pode(principal_de(quem), acao) is MATRIZ[(quem, acao)]


def test_matriz_cobre_todo_papel_e_toda_acao():
    """Papel ou acao nova sem decisao explicita falha aqui, nao em producao."""
    esperado = {(q, a) for q in [*Papel, PLATAFORMA] for a in Acao}
    assert set(MATRIZ) == esperado


def test_toda_acao_tem_exatamente_um_eixo():
    assert set(Acao) == ACOES_DE_TENANT | ACOES_DE_PLATAFORMA
    assert not ACOES_DE_TENANT & ACOES_DE_PLATAFORMA


@pytest.mark.parametrize("acao", sorted(ACOES_DE_TENANT, key=repr))
def test_plataforma_negada_em_toda_acao_de_tenant(acao):
    """Segunda invariante da spec: um papel que enxerga tudo vira teatro."""
    assert pode(Principal.de_plataforma(uuid4()), acao) is False


@pytest.mark.parametrize("papel", sorted(Papel, key=repr))
def test_servico_tem_exatamente_o_que_o_dono_tem(papel):
    """Token de servico nunca excede o dono — e nunca fica aquem."""
    dono, tenant = uuid4(), uuid4()
    usuario = Principal.de_usuario(dono, tenant, papel)
    servico = Principal.de_servico(dono, uuid4(), tenant, papel)
    for acao in Acao:
        assert pode(servico, acao) is pode(usuario, acao)


@pytest.mark.parametrize("papel", sorted(Papel, key=repr))
def test_todo_papel_de_tenant_ve_a_saude_da_propria_protecao(papel):
    """E produto, nao extra: e o que a tela inicial responde."""
    assert pode(principal_de(papel), Acao.VER_SAUDE_TENANT) is True


@pytest.mark.parametrize("papel", sorted(Papel, key=repr))
def test_nenhum_papel_de_tenant_ve_a_saude_da_infraestrutura(papel):
    """Agregar tenants expoe a existencia de outros clientes — vazamento sem
    que nenhuma linha de dado alheio apareca."""
    assert pode(principal_de(papel), Acao.VER_SAUDE_PLATAFORMA) is False


def test_plataforma_nao_ve_a_protecao_de_um_tenant():
    """Para isso precisa de papel concedido dentro daquele tenant."""
    p = Principal.de_plataforma(uuid4())
    assert pode(p, Acao.VER_SAUDE_TENANT) is False
    assert pode(p, Acao.VER_SAUDE_PLATAFORMA) is True


def test_so_disparar_failover_e_destrutiva():
    assert e_destrutiva(Acao.DISPARAR_FAILOVER) is True
    for acao in Acao:
        if acao is not Acao.DISPARAR_FAILOVER:
            assert e_destrutiva(acao) is False


def test_test_failover_nao_e_destrutivo():
    """Se virasse destrutivo, operator perderia o que a spec lhe deu."""
    assert e_destrutiva(Acao.RODAR_TEST_FAILOVER) is False
    assert pode(principal_de(Papel.OPERATOR), Acao.RODAR_TEST_FAILOVER) is True


def test_principal_e_imutavel():
    p = Principal.de_usuario(uuid4(), uuid4(), Papel.VIEWER)
    with pytest.raises(FrozenInstanceError):
        p.papel = Papel.ADMIN  # type: ignore[misc]


def test_plataforma_com_tenant_e_recusado():
    """O atalho que a spec proibe: plataforma nao tem onde carregar tenant."""
    with pytest.raises(PrincipalInvalidoError):
        Principal(
            origem=Origem.USUARIO,
            usuario_id=uuid4(),
            tenant_id=uuid4(),
            plataforma=True,
        )


def test_plataforma_com_papel_de_tenant_e_recusado():
    with pytest.raises(PrincipalInvalidoError):
        Principal(
            origem=Origem.USUARIO,
            usuario_id=uuid4(),
            papel=Papel.ADMIN,
            plataforma=True,
        )


def test_principal_de_tenant_sem_papel_e_recusado():
    with pytest.raises(PrincipalInvalidoError):
        Principal(origem=Origem.USUARIO, usuario_id=uuid4(), tenant_id=uuid4())


def test_principal_de_tenant_sem_tenant_e_recusado():
    with pytest.raises(PrincipalInvalidoError):
        Principal(origem=Origem.USUARIO, usuario_id=uuid4(), papel=Papel.VIEWER)


def test_servico_sem_servico_id_e_recusado():
    with pytest.raises(PrincipalInvalidoError):
        Principal(
            origem=Origem.SERVICO,
            usuario_id=uuid4(),
            tenant_id=uuid4(),
            papel=Papel.VIEWER,
        )


def test_usuario_com_servico_id_e_recusado():
    """Se a origem diz usuario, nao ha servico de quem herdar autoridade."""
    with pytest.raises(PrincipalInvalidoError):
        Principal(
            origem=Origem.USUARIO,
            usuario_id=uuid4(),
            servico_id=uuid4(),
            tenant_id=uuid4(),
            papel=Papel.VIEWER,
        )


def test_servico_guarda_o_dono_em_usuario_id():
    """A auditoria precisa do humano por tras do token (P6, P8)."""
    dono = uuid4()
    servico = Principal.de_servico(dono, uuid4(), uuid4(), Papel.ADMIN)
    assert servico.usuario_id == dono
    assert servico.origem is Origem.SERVICO
