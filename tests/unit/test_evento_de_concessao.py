"""A decisão entre os dois eventos de concessão, testada sem banco.

Ela vive num lugar só de propósito: chamador que precisa lembrar é chamador que
esquece.
"""

from uuid import uuid4

import pytest

from vzdr.core.domain.tenancy import Papel, Principal
from vzdr.core.tenancy.papeis import (
    EVENTO_AUTOCONCEDIDO,
    EVENTO_CONCEDIDO,
    evento_de,
)


def admin_de(usuario, tenant=None):
    return Principal.de_usuario(usuario, tenant or uuid4(), Papel.ADMIN)


def test_conceder_a_outro_e_concessao():
    assert evento_de(admin_de(uuid4()), uuid4()) == EVENTO_CONCEDIDO


def test_conceder_a_si_mesmo_e_autoconcessao():
    quem = uuid4()
    assert evento_de(admin_de(quem), quem) == EVENTO_AUTOCONCEDIDO


def test_nunca_os_dois():
    quem = uuid4()
    for beneficiario in (quem, uuid4()):
        assert evento_de(admin_de(quem), beneficiario) in {
            EVENTO_CONCEDIDO,
            EVENTO_AUTOCONCEDIDO,
        }


def test_por_token_de_servico_o_dono_e_quem_conta():
    """O serviço herda a autoridade do dono; conceder ao dono é auto-concessão,
    mesmo o pedido vindo por token."""
    dono, tenant = uuid4(), uuid4()
    servico = Principal.de_servico(dono, uuid4(), tenant, Papel.ADMIN)
    assert evento_de(servico, dono) == EVENTO_AUTOCONCEDIDO
    assert evento_de(servico, uuid4()) == EVENTO_CONCEDIDO


@pytest.mark.parametrize("evento", [EVENTO_CONCEDIDO, EVENTO_AUTOCONCEDIDO])
def test_os_nomes_seguem_a_convencao(evento):
    """ADR-0005: `dominio.acao`, no passado, em snake_case."""
    dominio, _, acao = evento.partition(".")
    assert dominio == "tenancy"
    assert acao.endswith("concedido")
    assert acao.islower()
