"""O checador da declaracao de revisao, incluindo o que ele NAO promete.

Cada caso de falha tem teste, porque checador que nunca reprovou e afirmacao,
nao verificacao. E um dos testes existe para fixar a fronteira: declaracao
mentirosa PASSA, e isso e deliberado — o nome do checador diz "respondida", nao
"verdadeira".
"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_declaracao_de_revisao import verificar  # noqa: E402

RESPONDIDA = """Corpo qualquer.

## Declaracao de revisao

- **Revisou o diff**: k1silva
- **Humano leu o diff**: sim
- **Clique do merge delegado**: nao
"""


def test_declaracao_respondida_passa():
    assert verificar(RESPONDIDA) == []


def test_o_proprio_template_reprova():
    """O template nao respondido tem que reprovar, senao ele nao serve de nada.

    E o teste que prova que a estrutura funciona: a linha fica ate alguem
    apaga-la, e o checador so aceita depois de apagada.
    """
    template = (RAIZ / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    falhas = verificar(template)
    assert len(falhas) == 3


def test_corpo_sem_a_secao_reprova():
    falhas = verificar("Consertei um bug. Nada mais.")
    assert len(falhas) == 3
    assert all("nao esta no corpo do PR" in f for f in falhas)


@pytest.mark.parametrize(
    "rotulo",
    ["Revisou o diff", "Humano leu o diff", "Clique do merge delegado"],
)
def test_faltar_uma_linha_reprova(rotulo):
    """Duas de tres respondidas nao e parcialmente ok — e reprovado.

    A terceira e justamente a que alguem esqueceria.
    """
    corpo = "\n".join(linha for linha in RESPONDIDA.splitlines() if rotulo not in linha)
    falhas = verificar(corpo)
    assert len(falhas) == 1
    assert rotulo in falhas[0]


def test_resposta_vazia_reprova():
    corpo = RESPONDIDA.replace("**Revisou o diff**: k1silva", "**Revisou o diff**:")
    assert any("sem resposta" in f for f in verificar(corpo))


def test_sim_ou_nao_com_lixo_em_volta_passa():
    """A pessoa escreve prosa; o que importa e a resposta estar la."""
    corpo = RESPONDIDA.replace(
        "**Humano leu o diff**: sim",
        "**Humano leu o diff**: sim, o Kawan leu na quinta",
    )
    assert verificar(corpo) == []


def test_resposta_que_nao_responde_reprova():
    """ "talvez" nao e sim nem nao, e a pergunta nao admite terceiro valor."""
    corpo = RESPONDIDA.replace("**Humano leu o diff**: sim", "**Humano leu o diff**: talvez")
    falhas = verificar(corpo)
    assert len(falhas) == 1
    assert "nao reconhecida" in falhas[0]


def test_acento_em_nao_e_aceito():
    corpo = RESPONDIDA.replace("**Humano leu o diff**: sim", "**Humano leu o diff**: não")
    assert verificar(corpo) == []


def test_declaracao_mentirosa_passa_e_isso_e_deliberado():
    """A FRONTEIRA do checador, fixada em teste.

    Ele confere que a linha foi respondida. Nao confere que a resposta e
    verdadeira, e nunca vai: "um humano leu o diff" nao e fato do repositorio.

    Se um dia alguem tentar fazer este checador afirmar mais do que verifica,
    este teste e onde a conversa comeca — e o nome do arquivo tem que mudar
    junto.
    """
    mentira = RESPONDIDA.replace("**Humano leu o diff**: sim", "**Humano leu o diff**: sim")
    assert verificar(mentira) == []
