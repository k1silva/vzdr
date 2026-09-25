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


def test_declaracao_que_se_contradiz_passa_e_isso_e_deliberado():
    """A FRONTEIRA do checador, fixada com uma entrada que a exercita.

    Declaracao MENTIROSA nao e expressavel como entrada: ela e byte a byte
    identica a uma honesta, e e exatamente isso que faz o checador nao poder
    distingui-las. Um teste "da mentira" so pode ser uma copia do caso feliz com
    outro nome — foi o que a primeira versao deste teste era.

    O que E expressavel, e prova a mesma fronteira, e uma declaracao
    internamente CONTRADITORIA: as duas primeiras linhas se contradizem e o
    checador aceita, porque ele le a forma e nao o sentido.

    Se um dia alguem quiser que ele cruze as respostas entre si, este teste e
    onde a conversa comeca — e o nome do arquivo muda junto.
    """
    contraditoria = """
- **Revisou o diff**: ninguem, o PR foi mesclado sem leitura
- **Humano leu o diff**: sim
- **Clique do merge delegado**: nao
"""
    assert verificar(contraditoria) == []


def test_rotulo_repetido_reprova():
    """Corpo que CITA o template antes de responder e o caso real aqui.

    Com duas ocorrencias, pegar a primeira e escolher em silencio — e se a
    citada estiver respondida num exemplo, um PR que nao respondeu passa. Esse e
    o modo de falha que importa, entao ambiguidade reprova.
    """
    corpo = RESPONDIDA + "\n\nComo diz o template:\n\n- **Humano leu o diff**: `<sim/nao>`\n"
    falhas = verificar(corpo)
    assert len(falhas) == 1
    assert "aparece 2 vezes" in falhas[0]


def test_rotulo_repetido_reprova_mesmo_quando_as_duas_respondem():
    """Nao e sobre a segunda estar por responder: e sobre haver duas."""
    corpo = RESPONDIDA + "\n- **Revisou o diff**: outra pessoa\n"
    assert any("aparece 2 vezes" in f for f in verificar(corpo))


CITACAO_CERCADA = (
    RESPONDIDA
    + """
Como o template pede:

```markdown
- **Revisou o diff**: `<quem>`
- **Humano leu o diff**: `<sim/nao>`
- **Clique do merge delegado**: `<sim/nao>`
```
"""
)

CITACAO_INDENTADA = (
    RESPONDIDA
    + """
Como o template pede:

    - **Revisou o diff**: `<quem>`
    - **Humano leu o diff**: `<sim/nao>`
"""
)


def test_citacao_em_bloco_cercado_nao_conta():
    """PR que mexe nesta regra e justamente quem mais cita o template.

    A alternativa era pedir que ninguem escrevesse o rotulo literal —
    disciplina, que este projeto troca por estrutura sempre que da.
    """
    assert verificar(CITACAO_CERCADA) == []


def test_citacao_indentada_nao_conta():
    """Bloco indentado e a outra forma de citar em markdown.

    Cerca sozinha nao o alcanca; por isso o rotulo tem que comecar na margem.
    """
    assert verificar(CITACAO_INDENTADA) == []


def test_citar_em_prosa_continua_reprovando():
    """O afrouxamento tem limite: repeticao em prosa e ambiguidade real."""
    corpo = RESPONDIDA + "\nE mais abaixo:\n\n- **Humano leu o diff**: `<sim/nao>`\n"
    assert any("aparece 2 vezes" in f for f in verificar(corpo))


def test_declaracao_so_dentro_de_bloco_reprova_alto():
    """Quem puser a declaracao DE VERDADE dentro de uma cerca perde ela.

    Reprova com "nao esta no corpo", que e mensagem clara — nao passa em
    silencio, que seria o defeito.
    """
    corpo = "```\n" + RESPONDIDA + "\n```\n"
    falhas = verificar(corpo)
    assert len(falhas) == 3
    assert all("nao esta no corpo do PR" in f for f in falhas)


def test_cerca_sem_fechamento_nao_come_a_declaracao():
    """So bloco COMPLETO e removido.

    Cerca aberta e nao fechada comeria o resto do corpo, e com ele a declaracao
    de verdade — entao ela nao remove nada.
    """
    corpo = "Comecei um bloco e esqueci de fechar:\n\n```\nalgo\n\n" + RESPONDIDA
    assert verificar(corpo) == []
