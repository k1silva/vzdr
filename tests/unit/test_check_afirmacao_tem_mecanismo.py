"""O meta-checador sobre fixtures — nunca sobre o repositorio real.

Os testes aqui provam que cada regra reprova quando deve. O repositorio real e
assunto do build, e a primeira execucao sobre ele foi registrada a parte, depois
da previsao.
"""

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_afirmacao_tem_mecanismo import (  # noqa: E402
    afirmacoes_do_adr,
    afirmacoes_do_plano,
    ainda_nao_cobertos,
    referencias,
    sustentadas_por_candidata,
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
REGISTRO = "docs/validacao/2026-10-02-m9.md"
MEDICOES = (
    "| # | Medição | O que decide | Estado | Registro |\n"
    "|---|---|---|---|---|\n"
    "| M1 | vazao | horas | aberta | — |\n"
    "| M4 | bitmap | resync | aberta | — |\n"
    f"| M9 | leitura | campo | medida | `{REGISTRO}` |\n"
)
TESTE = "def test_relogio():\n    pass\n"
MAKEFILE = "invariants:\n\tpython tests/invariants/check_a.py\n"
AGENTS = "O `check_a.py` verifica a regra A.\n"


PENDENCIAS = """# Pendencias

## Abertas

### P-002 — aberta

## Candidatas

- **C-001 — Uma ideia sem forma.** Texto.

## Fechadas

- **C-009 — Ja resolvida.** Nao sustenta nada.
"""


def montar(
    tmp_path,
    plano=PLANO_OK,
    adr=ADR_OK,
    agents=AGENTS,
    makefile=MAKEFILE,
    tasks=TASKS,
    pendencias=PENDENCIAS,
    medicoes=MEDICOES,
):
    arquivos = {
        "docs/pendencias.md": pendencias,
        "specs/dr-001-dominio-ciclo/plan.md": plano,
        "specs/dr-001-dominio-ciclo/tasks.md": tasks,
        "docs/adr/0015-efeito-como-valor.md": adr,
        # O ADR-0012 e coberto e e onde as medicoes moram: as duas coisas.
        "docs/adr/0012-resposta-a-perda-de-bitmap.md": ADR_OK + "\n" + medicoes,
        REGISTRO: "# M9 — o registro\n",
        "docs/adr/0016-confianca-no-bitmap.md": ADR_OK,
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


def _medicao_ausente(texto_da_tabela: str) -> str:
    """Um id que a tabela NAO tem, derivado dela — nunca escrito a mao. Um id
    escrito a mao ja virou medicao real da fixture uma vez (M9), e o teste passou a
    medir outra coisa sem ninguem mexer nele."""
    ids = [int(m) for m in re.findall(r"^\| M(\d+) \|", texto_da_tabela, re.MULTILINE)]
    ausente = f"M{max(ids) + 1}"
    assert f"| {ausente} |" not in texto_da_tabela
    return ausente


def test_medicao_que_nao_existe_reprova(tmp_path):
    ausente = _medicao_ausente(MEDICOES)
    plano = PLANO_OK.replace("`M1`", f"`{ausente}`")
    falhas = verificar(montar(tmp_path, plano=plano))
    assert any(ausente in f and "medicao nao existe" in f for f in falhas), falhas


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


def test_referencias_reconhece_as_cinco_formas():
    texto = "`tests/unit/t.py::test_a`, `tests/invariants/check_b.py`, `M4`, `T7`, `C-001`, `alvo`"
    assert referencias(texto) == [
        "tests/unit/t.py::test_a",
        "tests/invariants/check_b.py",
        "M4",
        "T7",
        "C-001",
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


# ── O que nao e coberto e derivado, nao escrito ─────────────────────────────


def test_documento_novo_aparece_como_nao_coberto_sem_ninguem_lembrar(tmp_path):
    """A lista a mao deixava spec ou ADR novo nascer invisivel. Por subtracao, ele
    aparece no dia em que existe."""
    raiz = montar(tmp_path)
    (raiz / "docs/adr/0099-novo.md").write_text("# ADR novo\n", encoding="utf-8")
    (raiz / "specs/dr-099-nova").mkdir(parents=True)
    (raiz / "specs/dr-099-nova/spec.md").write_text("# spec\n", encoding="utf-8")
    faltam = ainda_nao_cobertos(raiz)
    assert "docs/adr/0099-novo.md" in faltam
    assert "specs/dr-099-nova/spec.md" in faltam


def test_coberto_e_molde_nao_aparecem(tmp_path):
    raiz = montar(tmp_path)
    (raiz / "specs/_template").mkdir(parents=True)
    (raiz / "specs/_template/plan.md").write_text("# molde\n", encoding="utf-8")
    (raiz / "docs/adr/template.md").write_text("# molde\n", encoding="utf-8")
    faltam = ainda_nao_cobertos(raiz)
    assert "specs/dr-001-dominio-ciclo/plan.md" not in faltam
    assert "docs/adr/0015-efeito-como-valor.md" not in faltam
    assert not any("template" in f for f in faltam)


# ── O AGENTS.md tambem e auditado, e nao so colhido ─────────────────────────


def test_checador_apagado_com_a_linha_do_agents_de_pe_reprova(tmp_path):
    """O espelho da regra 3. Checador fora do build E do disco, linha do AGENTS.md
    ainda de pe: a regra 3 nao dispara (nao esta no build) e, sem auditoria, a
    regra 2 tambem nao — tudo verde, e o AGENTS.md mentindo."""
    raiz = montar(tmp_path, makefile="invariants:\n")
    (raiz / "tests/invariants/check_a.py").unlink()
    (falha,) = verificar(raiz)
    assert falha.startswith("AGENTS.md:") and "check_a.py" in falha and "nao existe" in falha


def test_caminho_de_script_inexistente_no_agents_reprova(tmp_path):
    agents = AGENTS + "A porta unica e `scripts/porta_que_sumiu.py`.\n"
    assert any("porta_que_sumiu" in f for f in verificar(montar(tmp_path, agents=agents)))


def test_crase_que_nao_tem_forma_de_arquivo_no_agents_nao_e_auditada(tmp_path):
    """`make check`, `tenant_id`, `vzdr.core.domain` — nomes, nao arquivos."""
    agents = AGENTS + "Rode `make check`; o campo `tenant_id` mora em `vzdr.core.domain`.\n"
    assert verificar(montar(tmp_path, agents=agents)) == []


def test_mensagem_nao_promete_secao_que_nao_confere(tmp_path):
    """A primeira versao dizia "onde a regra que ele verifica e escrita", e o onde
    nunca foi conferido: qualquer crase em qualquer lugar satisfazia."""
    (falha,) = verificar(montar(tmp_path, agents="Nada.\n"))
    assert "onde a regra" not in falha and "em crase" in falha


# ── A quinta forma: candidata, so em afirmacao rebaixada ────────────────────


def _adr_com(titulo: str, mecanismo: str) -> str:
    return f"# ADR\n\n## Decisão\n\n### 1. {titulo}\n\n**Mecanismo:** {mecanismo}\n"


def test_candidata_que_existe_em_afirmacao_rebaixada_passa(tmp_path):
    raiz = montar(tmp_path, adr=_adr_com("A interface diz — **rebaixada**", "`C-001`"))
    assert verificar(raiz) == []


def test_candidata_que_nao_existe_reprova(tmp_path):
    raiz = montar(tmp_path, adr=_adr_com("A interface diz — **rebaixada**", "`C-002`"))
    assert any("C-002" in f and "nao ha candidata" in f for f in verificar(raiz))


def test_candidata_nao_sustenta_decisao_viva(tmp_path):
    """A guarda contra o abuso: candidata e barata, e decisao viva precisa de
    mecanismo de verdade."""
    raiz = montar(tmp_path, adr=_adr_com("A interface diz", "`C-001`"))
    assert any("so sustenta afirmacao rebaixada" in f for f in verificar(raiz))


def test_candidata_nao_sustenta_risco_de_plano(tmp_path):
    plano = PLANO_OK.replace("Medido em `M1`", "Um dia: `C-001`")
    raiz = montar(tmp_path, plano=plano)
    assert any("so sustenta afirmacao rebaixada" in f for f in verificar(raiz))


def test_id_fora_da_secao_de_candidatas_nao_conta(tmp_path):
    """C-009 esta em Fechadas: item resolvido nao sustenta afirmacao nenhuma."""
    raiz = montar(tmp_path, adr=_adr_com("A interface diz — **rebaixada**", "`C-009`"))
    assert any("C-009" in f for f in verificar(raiz))


def test_a_pressao_e_impressa_e_nao_reprova(tmp_path):
    """Contada so a afirmacao cujo unico sustento e candidata."""
    adr = _adr_com("A interface diz — **rebaixada**", "`C-001`") + (
        "\n### 2. Outra — **rebaixada**\n\n**Mecanismo:** `C-001`, `M1`\n"
    )
    raiz = montar(tmp_path, adr=adr)
    assert verificar(raiz) == []
    so_candidata = sustentadas_por_candidata(raiz)
    assert any("propriedade 1" in a for a in so_candidata), so_candidata
    assert not any("propriedade 2" in a for a in so_candidata), so_candidata


# ── O paragrafo do mecanismo, e nao so a primeira linha ─────────────────────


def test_referencia_na_linha_de_continuacao_e_lida():
    adr = "# A\n\n## Decisão\n\n### 1. X\n\n**Mecanismo:** ainda nao existe:\n`T7`, aberta.\n"
    assert afirmacoes_do_adr(adr) == [("propriedade 1: X", ["T7"])]


def test_referencia_quebrada_na_continuacao_reprova(tmp_path):
    """O sentido perigoso: a referencia a um teste que nao existe, na segunda linha,
    passava sem ser conferida."""
    adr = (
        "# A\n\n## Decisão\n\n### 1. X\n\n"
        "**Mecanismo:** `tests/unit/test_x.py::test_relogio` e,\n"
        "na linha seguinte, `tests/unit/test_x.py::test_que_nao_existe`.\n"
    )
    raiz = montar(tmp_path, adr=adr)
    assert any("test_que_nao_existe" in f for f in verificar(raiz))


def test_o_paragrafo_termina_na_linha_em_branco():
    """Texto depois do paragrafo do mecanismo nao vira mecanismo."""
    adr = (
        "# A\n\n## Decisão\n\n### 1. X\n\n**Mecanismo:** `T7`.\n\n"
        "Depois, uma prosa que cita `M4` de passagem.\n"
    )
    assert afirmacoes_do_adr(adr) == [("propriedade 1: X", ["T7"])]


# ── A volta da quinta forma: toda candidata carrega id ──────────────────────


def test_candidata_sem_id_reprova(tmp_path):
    """Sem id ela fica invisivel, e a referencia a ela diria que nao existe."""
    pendencias = PENDENCIAS.replace(
        "- **C-001 — Uma ideia sem forma.** Texto.",
        "- **C-001 — Uma ideia sem forma.** Texto.\n- **Outra ideia, sem id.** Texto.",
    )
    raiz = montar(tmp_path, pendencias=pendencias)
    assert any("candidata sem id" in f and "Outra ideia" in f for f in verificar(raiz))


def test_continuacao_de_item_nao_e_item(tmp_path):
    """So a linha que abre o item precisa do id; a continuacao indentada, nao."""
    pendencias = PENDENCIAS.replace(
        "- **C-001 — Uma ideia sem forma.** Texto.",
        "- **C-001 — Uma ideia sem forma.** Texto que\n  continua na linha de baixo.",
    )
    raiz = montar(tmp_path, pendencias=pendencias)
    assert verificar(raiz) == []


# ── Medicao em dois estados, e o registro como sexta forma ──────────────────


def test_medicao_aberta_citada_passa(tmp_path):
    assert verificar(montar(tmp_path, adr=_adr_com("X", "`M4`"))) == []


def test_medicao_feita_citada_como_m_reprova(tmp_path):
    """O bug que mordeu: a decisao dizia "ainda nao existe: M5" com a M5 medida."""
    raiz = montar(tmp_path, adr=_adr_com("X", "`M9`"))
    assert any("M9" in f and "cite" in f and REGISTRO in f for f in verificar(raiz))


def test_registro_de_medicao_feita_citado_passa(tmp_path):
    assert verificar(montar(tmp_path, adr=_adr_com("X", f"`{REGISTRO}`"))) == []


def test_registro_que_nao_existe_reprova(tmp_path):
    raiz = montar(tmp_path, adr=_adr_com("X", "`docs/validacao/nao-existe.md`"))
    assert any("nao-existe.md" in f and "nao existe" in f for f in verificar(raiz))


def test_arquivo_de_validacao_que_nao_e_registro_de_medicao_reprova(tmp_path):
    """Existir nao basta: tem que ser o que a tabela da como registro de uma medicao
    feita."""
    raiz = montar(tmp_path, adr=_adr_com("X", "`docs/validacao/outro.md`"))
    (raiz / "docs/validacao/outro.md").write_text("# M9 — outro\n", encoding="utf-8")
    assert any("outro.md" in f and "nenhuma medicao" in f for f in verificar(raiz))


def test_medida_sem_registro_na_mesma_linha_reprova(tmp_path):
    """A condicao que impede o bug de renascer um nivel acima: o estado "medida"
    sozinho seria um campo que diz "feito" e ninguem confere."""
    medicoes = MEDICOES.replace(f"medida | `{REGISTRO}` |", "medida | — |")
    raiz = montar(tmp_path, medicoes=medicoes)
    assert any("M9" in f and "sem registro" in f for f in verificar(raiz))


def test_aberta_com_registro_reprova(tmp_path):
    medicoes = MEDICOES.replace(
        "| M1 | vazao | horas | aberta | — |", f"| M1 | vazao | horas | aberta | `{REGISTRO}` |"
    )
    raiz = montar(tmp_path, medicoes=medicoes)
    assert any("M1" in f and "aberta, e com registro" in f for f in verificar(raiz))


def test_estado_desconhecido_reprova(tmp_path):
    medicoes = MEDICOES.replace(
        "| M4 | bitmap | resync | aberta |", "| M4 | bitmap | resync | quase |"
    )
    raiz = montar(tmp_path, medicoes=medicoes)
    assert any("M4" in f and "quase" in f for f in verificar(raiz))


def test_registro_que_nao_nomeia_a_medicao_reprova(tmp_path):
    raiz = montar(tmp_path)
    (raiz / REGISTRO).write_text("# um registro de outra coisa\n", encoding="utf-8")
    assert any("nao diz que responde a M9" in f for f in verificar(raiz))


def test_registro_que_nao_existe_na_tabela_reprova(tmp_path):
    raiz = montar(tmp_path)
    (raiz / REGISTRO).unlink()
    assert any("M9" in f and "nao existe" in f for f in verificar(raiz))


def test_celula_com_dois_registros_reprova(tmp_path):
    """Uma linha, um registro: a coluna nao vira lista."""
    medicoes = MEDICOES.replace(
        f"medida | `{REGISTRO}` |", f"medida | `{REGISTRO}`, `{REGISTRO}` |"
    )
    raiz = montar(tmp_path, medicoes=medicoes)
    assert any("uma linha, um registro" in f for f in verificar(raiz))


# ── A volta: registro -> tabela; e a leitura pelo cabecalho ─────────────────


def test_registro_orfao_reprova(tmp_path):
    """Mediu, escreveu o registro, esqueceu o estado: a tabela diz `aberta` e toda
    afirmacao segue citando M<n>. E quem esqueceu a celula que tem que ser pego."""
    raiz = montar(tmp_path)
    (raiz / "docs/validacao/2026-11-01-m4.md").write_text("# M4 — medida\n", encoding="utf-8")
    assert any("registro orfao" in f and "M4" in f for f in verificar(raiz))


def test_arquivo_de_validacao_sem_medicao_no_titulo_nao_e_registro(tmp_path):
    """O censo e a validacao cross-DC sao evidencia sem medicao do indice."""
    raiz = montar(tmp_path)
    (raiz / "docs/validacao/2026-09-23-censo.md").write_text(
        "# Censo do parque\n\nNao serve de proxy para a M2.\n", encoding="utf-8"
    )
    assert verificar(raiz) == []


def test_registro_que_cita_a_medicao_so_no_corpo_nao_responde_a_ela(tmp_path):
    """O registro da M5 cita M2 e M4 no corpo; "nomear em qualquer lugar" deixava
    uma linha M2 apontar para ele."""
    raiz = montar(tmp_path)
    (raiz / REGISTRO).write_text(
        "# M8 — outra medicao\n\nSobre a M9, de passagem.\n", encoding="utf-8"
    )
    falhas = verificar(raiz)
    assert any("titulo do registro" in f and "M9" in f for f in falhas), falhas


def test_colunas_lidas_pelo_nome_e_nao_pela_posicao(tmp_path):
    """Estado e Registro fora das duas ultimas posicoes continuam lidos certo. Uma
    versao anterior deste teste deixava Estado na penultima por acaso, e o arnes
    mostrou que a leitura por posicao passava nela."""
    medicoes = (
        "| # | Estado | Registro | Medição | O que decide |\n"
        "|---|---|---|---|---|\n"
        "| M1 | aberta | — | vazao | horas |\n"
        "| M4 | aberta | — | bitmap | resync |\n"
        f"| M9 | medida | `{REGISTRO}` | leitura | campo |\n"
    )
    assert verificar(montar(tmp_path, medicoes=medicoes)) == []


def test_linha_com_celulas_a_mais_reprova_e_nao_e_adivinhada(tmp_path):
    medicoes = MEDICOES.replace(
        "| M1 | vazao | horas | aberta | — |", "| M1 | vazao | horas | extra | aberta | — |"
    )
    raiz = montar(tmp_path, medicoes=medicoes)
    assert any("M1" in f and "estado ''" in f for f in verificar(raiz))


def test_medida_sem_registro_citada_nao_diz_none(tmp_path):
    medicoes = MEDICOES.replace(f"medida | `{REGISTRO}` |", "medida | — |")
    raiz = montar(tmp_path, adr=_adr_com("X", "`M9`"), medicoes=medicoes)
    falhas = verificar(raiz)
    assert any("M9" in f and "ainda nao tem registro" in f for f in falhas), falhas
    assert not any("None" in f for f in falhas), falhas
