"""A logica de alvo dos testes com banco, testada sem banco.

O caminho feliz de tests/db exige Postgres; o comportamento em falha, nao — e e ele
que impede rodar a suite contra a maquina errada.
"""

import pytest

from scripts.ambiente_db import (
    DSN_LOCAL,
    DSN_LOCAL_APP,
    HOSTS_LOCAIS,
    VARIAVEL,
    VARIAVEL_APP,
    VARIAVEL_REMOTO,
    BancoRecusadoError,
    dsn_verificado,
    host_de,
    mensagem_sem_banco,
    verificar_alvo,
)


def test_sem_variavel_usa_o_banco_do_compose():
    assert dsn_verificado({}) == DSN_LOCAL


def test_variavel_vence():
    dsn = "postgresql://outro:x@localhost:5433/outro"
    assert dsn_verificado({VARIAVEL: dsn}) == dsn


def test_variavel_vazia_cai_no_padrao():
    assert dsn_verificado({VARIAVEL: ""}) == DSN_LOCAL


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_host_local_passa(host):
    verificar_alvo(f"postgresql://vzdr:dev@{host}:5432/vzdr", {})


def test_host_remoto_e_recusado():
    dsn = "postgresql://vzdr:dev@db-prod.interno:5432/vzdr"
    with pytest.raises(BancoRecusadoError) as erro:
        verificar_alvo(dsn, {})
    assert "db-prod.interno" in str(erro.value)
    assert VARIAVEL_REMOTO in str(erro.value)


def test_host_remoto_passa_com_autorizacao_explicita():
    dsn = "postgresql://vzdr:dev@db-lab.interno:5432/vzdr"
    verificar_alvo(dsn, {VARIAVEL_REMOTO: "1"})


def test_autorizacao_so_vale_com_o_valor_exato():
    """'true', 'sim' ou vazio nao autorizam — so '1'."""
    dsn = "postgresql://vzdr:dev@db-lab.interno:5432/vzdr"
    for valor in ["true", "sim", "", "0", "yes"]:
        with pytest.raises(BancoRecusadoError):
            verificar_alvo(dsn, {VARIAVEL_REMOTO: valor})


def test_mensagem_sem_banco_preserva_o_erro_cru():
    """P8: o log guarda a falha original, nunca so uma mensagem generica."""
    erro = ConnectionRefusedError(111, "Connection refused")
    msg = mensagem_sem_banco(DSN_LOCAL, erro)
    assert "make db-up" in msg
    assert "Connection refused" in msg
    assert DSN_LOCAL in msg


def test_resolver_e_verificar_sao_a_mesma_operacao():
    """Não há como obter uma DSN sem a guarda: pedir uma remota levanta.

    Enquanto eram duas funções, chamar a guarda era disciplina de quem
    escrevesse o próximo `main()`.
    """
    with pytest.raises(BancoRecusadoError):
        dsn_verificado({VARIAVEL: "postgresql://vzdr:dev@db-prod.interno:5432/vzdr"})


def test_dsn_do_papel_da_aplicacao_tambem_passa_pela_guarda():
    with pytest.raises(BancoRecusadoError):
        dsn_verificado(
            {VARIAVEL_APP: "postgresql://vzdr_app:dev@db-prod.interno:5432/vzdr"},
            app=True,
        )


def test_a_senha_de_laboratorio_so_aparece_em_dsn_local():
    """Se alguém mover as DSN para variável de ambiente, a senha escrita aqui
    passa a poder alcançar um banco real. Este teste amarra as duas coisas."""
    for dsn in (DSN_LOCAL, DSN_LOCAL_APP):
        assert host_de(dsn) in HOSTS_LOCAIS
