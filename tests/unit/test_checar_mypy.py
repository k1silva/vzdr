"""A guarda contra secao de configuracao inerte do mypy.

O ponto todo dela e que o mypy sai com codigo 0 nesse caso. Os testes cobrem
exatamente essa passagem: saida limpa do mypy, mas nota de secao orfa.
"""

import pytest

from scripts.checar_mypy import MARCA, decidir, verificar_config

CONFIG_OK = {"tool": {"mypy": {"warn_unused_configs": True}}}


def test_sucesso_limpo_passa():
    assert decidir(0, "Success: no issues found in 16 source files\n") == (0, "")


def test_erro_do_mypy_passa_adiante():
    codigo, extra = decidir(1, "arquivo.py:1: error: algo\n")
    assert codigo == 1
    assert extra == ""


def test_secao_inerte_falha_mesmo_com_mypy_em_zero():
    """O caso que motivou a guarda: mypy verde, regra não aplicada."""
    saida = (
        "pyproject.toml: note: unused section(s): module = ['vzdr.core.domain.*']\n"
        "Success: no issues found in 16 source files\n"
    )
    codigo, extra = decidir(0, saida)
    assert codigo == 1
    assert "MYPYPATH" in extra


def test_secao_inerte_vale_para_qualquer_override():
    """Não é só a do domínio: override órfão de qualquer pacote conta."""
    saida = "pyproject.toml: note: unused section(s): module = ['vzdr.core.jobs.*']\n"
    assert decidir(0, saida)[0] == 1


def test_secao_inerte_junto_com_erro_continua_falhando():
    saida = f"x.py:1: error: algo\npyproject.toml: note: {MARCA}(s): module = ['a.*']\n"
    assert decidir(1, saida)[0] == 1


def test_texto_parecido_nao_dispara():
    """Não confundir com código do projeto que mencione a expressão."""
    assert decidir(0, "Success: no issues found in 1 source file\n") == (0, "")


def test_config_boa_nao_reclama():
    assert verificar_config(CONFIG_OK) == ""


@pytest.mark.parametrize(
    "config",
    [
        {"tool": {"mypy": {"warn_unused_configs": False}}},
        {"tool": {"mypy": {}}},
        {"tool": {}},
        {},
    ],
)
def test_guarda_desarmada_e_recusada(config):
    """Desligar warn_unused_configs desarma a guarda — e isso tem que doer."""
    assert "warn_unused_configs" in verificar_config(config)


def test_o_pyproject_de_verdade_mantem_a_guarda_armada():
    import tomllib
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    dados = tomllib.loads((raiz / "pyproject.toml").read_text("utf-8"))
    assert verificar_config(dados) == ""
