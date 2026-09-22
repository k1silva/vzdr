"""O minimo que prova que a pasta tests/db esta de pe e falando com o banco certo."""

import pytest

pytestmark = pytest.mark.db


def test_conecta_e_responde(conexao):
    with conexao.cursor() as cur:
        cur.execute("select 1")
        assert cur.fetchone() == (1,)


def test_o_banco_e_o_do_compose(conexao, dsn):
    """Guarda contra rodar a suite contra um banco que nao e o de desenvolvimento."""
    with conexao.cursor() as cur:
        cur.execute("select current_database()")
        (nome,) = cur.fetchone()
    assert nome in dsn
