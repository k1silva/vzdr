"""O meta-checador sobre fixtures — nunca sobre o repositorio real.

Os testes aqui provam que cada regra reprova quando deve. O repositorio real e
assunto do build, e a primeira execucao sobre ele foi registrada a parte, depois
da previsao.
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_afirmacao_tem_mecanismo import (  # noqa: E402
    afirmacoes_do_adr,
    afirmacoes_do_plano,
    referencias,
    verificar,
)

PLANO_OK = """# Plano

## Riscos

| Risco | Mitigação |
| --- | --- |
| Relogio lido por dentro | `tests/unit/test_x.py::test_relogio` |
| Liberacao por lease | Ainda nao existe: `T7` |
| Tamanho do seed | Medido em `M1` |

## Outra
"""

ADR_OK = """# ADR

## Decisão

### 1. Serializavel

Texto.

**Mecanismo:** `tests/unit/test_x.py::test_relogio`

## Consequências
"""

TASKS = "- [x] **T2** — feita\n- [ ] **T7** — aberta\n"
MEDICOES = "| M1 | vazao |\n| M4 | bitmap |\n"
TESTE = "def test_relogio():\n    pass\n"
MAKEFILE = "invariants:\n\tpython tests/invariants/check_a.py\n"
AGENTS = "O `check_a.py` verifica a regra A.\n"


def montar(tmp_path, plano=PLANO_OK, adr=ADR_OK, agents=AGENTS, makefile=MAKEFILE, tasks=TASKS):
    arquivos = {
        "specs/dr-001-dominio-ciclo/plan.md": plano,
        "specs/dr-001-dominio-ciclo/tasks.md": tasks,
        "docs/adr/0015-efeito-como-valor.md": adr,
        "docs/adr/0012-resposta-a-perda-de-bitmap.md": MEDICOES,
        "tests/unit/test_x.py": TESTE,
        "tests/invariants/check_a.py": "",
        "AGENTS.md": agents,
        "Makefile": makefile,
    }
    for caminho, texto in arquivos.items():
        (tmp_path / caminho).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / caminho).write_text(texto, encoding="utf-8")
    return tmp_path


def test_tudo_reivindicado_e_existente_passa(tmp_path):
    assert verificar(montar(tmp_path)) == []


# ── regra 1: afirmacao nomeia mecanismo ─────────────────────────────────────


def test_risco_em_prosa_reprova(tmp_path):
    """A mitigacao que cita uma intencao, e nao um mecanismo."""
    plano = PLANO_OK.replace("Medido em `M1`", "O plano ja diz que nao")
    (falha,) = verificar(montar(tmp_path, plano=plano))
    assert "Tamanho do seed" in falha and "nao nomeia mecanismo" in falha


def test_crase_que_nao_e_mecanismo_nao_conta(tmp_path):
    """`alvo` entre crases e nome de campo, nao mecanismo."""
    plano = PLANO_OK.replace("Medido em `M1`", "`alvo` e campo do efeito")
    assert any("nao nomeia mecanismo" in f for f in verificar(montar(tmp_path, plano=plano)))


def test_propriedade_de_adr_sem_linha_de_mecanismo_reprova(tmp_path):
    adr = ADR_OK.replace("**Mecanismo:** `tests/unit/test_x.py::test_relogio`\n", "")
    (falha,) = verificar(montar(tmp_path, adr=adr))
    assert "propriedade 1" in falha


def test_documento_coberto_sem_afirmacao_reprova(tmp_path):
    """Estrutura que mudou de nome — `## Riscos` virou outra coisa — nao pode fazer o
    checador passar por nao achar nada."""
    plano = PLANO_OK.replace("## Riscos", "## Perigos")
    assert any("nenhuma afirmacao" in f for f in verificar(montar(tmp_path, plano=plano)))


# ── regra 2: mecanismo nomeado existe ───────────────────────────────────────


def test_teste_que_nao_existe_reprova(tmp_path):
    plano = PLANO_OK.replace("test_relogio`", "test_que_ninguem_escreveu`", 1)
    assert any("funcao nao existe" in f for f in verificar(montar(tmp_path, plano=plano)))


def test_arquivo_de_teste_que_nao_existe_reprova(tmp_path):
    plano = PLANO_OK.replace("tests/unit/test_x.py::", "tests/unit/test_y.py::", 1)
    assert any("arquivo nao existe" in f for f in verificar(montar(tmp_path, plano=plano)))


def test_medicao_que_nao_existe_reprova(tmp_path):
    plano = PLANO_OK.replace("`M1`", "`M9`")
    assert any("medicao nao existe" in f for f in verificar(montar(tmp_path, plano=plano)))


def test_tarefa_feita_ainda_citada_como_mecanismo_reprova(tmp_path):
    """`T<n>` e declaracao de que o mecanismo ainda nao existe. Tarefa feita com a
    afirmacao ainda apontando para ela: o mecanismo tinha que ter sido nomeado."""
    tasks = TASKS.replace("- [ ] **T7**", "- [x] **T7**")
    assert any("tarefa esta feita" in f for f in verificar(montar(tmp_path, tasks=tasks)))


def test_tarefa_que_nao_existe_reprova(tmp_path):
    plano = PLANO_OK.replace("`T7`", "`T99`")
    assert any("tarefa nao existe" in f for f in verificar(montar(tmp_path, plano=plano)))


# ── regra 3, a volta: checador no build e reivindicado ──────────────────────


def test_checador_no_build_sem_reivindicacao_reprova(tmp_path):
    """A metade que se esquece. Sem ela acumulam checadores orfaos."""
    (falha,) = verificar(montar(tmp_path, agents="Nada nomeado aqui.\n"))
    assert "check_a.py" in falha and "nenhuma afirmacao o reivindica" in falha


def test_checador_reivindicado_por_documento_coberto_passa(tmp_path):
    plano = PLANO_OK.replace("Medido em `M1`", "Verificado por `tests/invariants/check_a.py`")
    assert verificar(montar(tmp_path, plano=plano, agents="Nada.\n")) == []


def test_mencao_sem_crase_no_agents_nao_reivindica(tmp_path):
    """Por estrutura, nunca por mencao solta."""
    assert verificar(montar(tmp_path, agents="O check_a.py verifica.\n"))


# ── as bordas de leitura ────────────────────────────────────────────────────


def test_tabela_citada_em_bloco_de_codigo_nao_conta():
    texto = "## Riscos\n\n```\n| R | sem mecanismo |\n```\n| R2 | `M1` |\n"
    assert afirmacoes_do_plano(texto) == [("R2", ["M1"])]


def test_mecanismo_fora_de_decisao_nao_conta():
    texto = "## Decisão\n\n### 1. A\n\n## Consequências\n\n**Mecanismo:** `M1`\n"
    assert afirmacoes_do_adr(texto) == [("propriedade 1: A", [])]


def test_referencias_reconhece_as_quatro_formas():
    texto = "`tests/unit/t.py::test_a`, `tests/invariants/check_b.py`, `M4`, `T7`, `alvo`"
    assert referencias(texto) == [
        "tests/unit/t.py::test_a",
        "tests/invariants/check_b.py",
        "M4",
        "T7",
    ]


def test_cerca_de_codigo_antes_da_reivindicacao_nao_a_esconde(tmp_path):
    """O defeito da primeira execucao real. Pareando crases no arquivo inteiro, a
    cerca de tres crases deslocava todos os pares seguintes, e tres checadores
    nomeados no AGENTS.md sairam como orfaos."""
    agents = "Comandos:\n\n```bash\nmake check\n```\n\nO `check_a.py` verifica a regra A.\n"
    assert verificar(montar(tmp_path, agents=agents)) == []


def test_nome_dentro_de_bloco_de_codigo_nao_reivindica(tmp_path):
    agents = "```\nO `check_a.py` verifica.\n```\n"
    assert verificar(montar(tmp_path, agents=agents))


def test_tarefa_solta_num_adr_reprova(tmp_path):
    """Num ADR, `T7` nao diz de qual spec e a tarefa."""
    adr = ADR_OK.replace("`tests/unit/test_x.py::test_relogio`", "`T7`")
    assert any("tarefa sem spec" in f for f in verificar(montar(tmp_path, adr=adr)))


def test_tarefa_qualificada_num_adr_passa(tmp_path):
    adr = ADR_OK.replace("`tests/unit/test_x.py::test_relogio`", "`dr-001/T7`")
    assert verificar(montar(tmp_path, adr=adr)) == []


def test_tarefa_qualificada_feita_reprova(tmp_path):
    adr = ADR_OK.replace("`tests/unit/test_x.py::test_relogio`", "`dr-001/T2`")
    assert any("tarefa esta feita" in f for f in verificar(montar(tmp_path, adr=adr)))
