"""A regra de senha do papel da aplicação.

Não existe senha padrão. Senha padrão que funciona é como credencial de
laboratório chega em produção: ninguém percebe que nunca a trocou, porque nada
nunca falhou.
"""

import pytest

from scripts.criar_papeis_db import (
    VARIAVEL_SENHA,
    SenhaAusenteError,
    senha_para_criar,
)


def test_senha_fornecida_e_usada():
    assert senha_para_criar("segredo") == "segredo"


@pytest.mark.parametrize("valor", [None, ""])
def test_sem_senha_levanta_em_vez_de_inventar_uma(valor):
    with pytest.raises(SenhaAusenteError) as erro:
        senha_para_criar(valor)
    assert VARIAVEL_SENHA in str(erro.value)


def test_a_mensagem_diz_os_dois_caminhos():
    """Quem tropeça às três da manhã precisa saber o que fazer, não só o quê."""
    with pytest.raises(SenhaAusenteError) as erro:
        senha_para_criar(None)
    texto = str(erro.value)
    assert "make db-up" in texto
    assert "docker-compose.yml" in texto
