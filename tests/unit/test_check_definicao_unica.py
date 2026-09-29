"""O checador de definicao unica, e as fronteiras dele fixadas em teste."""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_definicao_unica import definicoes, verificar  # noqa: E402

# As duas linhas REAIS, copiadas literalmente de onde estavam no main quando o
# checador nasceu. A primeira execucao dele foi vermelha sobre elas, e este e o
# registro permanente disso: nao depende de o repositorio continuar com a
# contradicao, e reprova se o checador perder a capacidade de ve-la.
DR001_REAL = "## `degradada` é derivada, não marcada\n"
DR006_REAL = "- `degradada` — ciclo ativo mas fora do RPO, ou último ciclo falhou\n"


def montar(tmp_path: Path, specs: dict) -> Path:
    for nome, texto in specs.items():
        pasta = tmp_path / "specs" / nome
        pasta.mkdir(parents=True)
        (pasta / "spec.md").write_text(texto, encoding="utf-8")
    return tmp_path


def test_aceitacao_a_contradicao_real_de_degradada(tmp_path):
    """O teste de aceitacao: a primeira execucao do checador, preservada.

    Titulo numa spec, lista na outra. Com so uma das duas formas, o checador
    nasceria verde — a dr-001 nao tinha NENHUMA definicao em lista.
    """
    raiz = montar(tmp_path, {"dr-001": DR001_REAL, "dr-006": DR006_REAL})
    (falha,) = verificar(raiz)
    assert "`degradada` definido 2 vezes" in falha
    assert "dr-001/spec.md:1" in falha and "dr-006/spec.md:1" in falha


def test_uma_definicao_passa(tmp_path):
    raiz = montar(tmp_path, {"dr-001": DR001_REAL, "dr-006": "Ver a dr-001 para `degradada`.\n"})
    assert verificar(raiz) == []


def test_duas_na_mesma_spec_tambem_reprova(tmp_path):
    """Dentro da mesma spec, duas definicoes podem discordar do mesmo jeito."""
    raiz = montar(tmp_path, {"dr-001": DR001_REAL + "\n" + DR006_REAL})
    assert len(verificar(raiz)) == 1


@pytest.mark.parametrize(
    "linha",
    [
        "- `termo` — definicao\n",
        "- `termo` – com meia-risca\n",
        "* `termo` — com asterisco\n",
        "## `termo`\n",
        "### `termo` e outras palavras\n",
    ],
)
def test_formas_que_contam(linha):
    assert definicoes(linha) == [("termo", 1)]


@pytest.mark.parametrize(
    "linha",
    [
        # mencao em prosa
        "O estado `termo` aparece aqui.\n",
        # lista sem travessao: e a forma de dr-001:484, "- `degradada` e calculada"
        "- `termo` é calculada, nunca guardada.\n",
        # titulo que nao ABRE com o termo
        "## Sobre `termo`\n",
        # titulo de nivel 1 e o nome do documento, nao definicao
        "# `termo`\n",
        # tabela: limite declarado
        "| `termo` | definicao |\n",
        # lista indentada: e sub-item, nao definicao de topo
        "  - `termo` — sub-item\n",
    ],
)
def test_formas_que_nao_contam(linha):
    assert definicoes(linha) == []


@pytest.mark.parametrize("cerca", ["```", "~~~", "````"])
def test_definicao_citada_em_bloco_de_codigo_nao_conta(cerca):
    texto = f"Como a dr-006 dizia:\n\n{cerca}\n{DR006_REAL}{cerca}\n"
    assert definicoes(texto) == []


def test_citacao_com_o_mesmo_texto_da_definicao_conta_uma_vez():
    """O defeito que quase entrou.

    A primeira versao decidia o que estava fora de bloco comparando TEXTO de
    linha. A definicao real e a citada numa cerca tem o mesmo texto, e as duas
    contavam — falso positivo justamente no caso "citei a definicao".
    """
    texto = f"{DR006_REAL}\nComo escrito acima:\n\n```\n{DR006_REAL}```\n"
    assert definicoes(texto) == [("degradada", 1)]


def test_o_limite_prosa_nos_dois_lados_passa(tmp_path):
    """O LIMITE mais importante, fixado.

    Conceito definido em prosa nas duas specs nao e pego. E exatamente como
    `degradada` chegou ate aqui — e so foi pego porque, por acaso, uma spec usou
    titulo e a outra lista. Para prosa existe a pergunta de revisao do AGENTS.md.
    Se um dia alguem quiser que o checador pegue isto, este teste e onde a
    conversa comeca: o caminho e busca por mencao, e mencao e falso positivo em
    serie.
    """
    raiz = montar(
        tmp_path,
        {
            "dr-001": "A VM fica degradada quando o ponto passa de 2x o RPO.\n",
            "dr-006": "A VM fica degradada quando o ultimo ciclo falha.\n",
        },
    )
    assert verificar(raiz) == []


def test_plano_e_tarefas_nao_sao_lidos(tmp_path):
    """A definicao mora na spec. Restatear no plano e normal."""
    raiz = montar(tmp_path, {"dr-001": DR001_REAL})
    (raiz / "specs" / "dr-001" / "plan.md").write_text(DR001_REAL, encoding="utf-8")
    assert verificar(raiz) == []


def test_mensagem_aponta_o_conserto(tmp_path, capsys, monkeypatch):
    import check_definicao_unica as modulo

    raiz = montar(tmp_path, {"a": DR001_REAL, "b": DR006_REAL})
    monkeypatch.setattr(modulo, "RAIZ", raiz)
    assert modulo.main() == 1
    saida = capsys.readouterr().out
    assert "aponte para la" in saida and "arbitre por regra" in saida
