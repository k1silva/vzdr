"""O checador que mantém a regra do registro de pendências viva.

Ele é o único deste repositório que falha por causa do tempo passar, e não do
que alguém mudou. Os testes cobrem as duas formas de a regra morrer: o prazo
vencido que ninguém vê, e a renovação que vira carimbo.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_pendencias import ARQUIVO, MAX_RENOVACOES, itens, verificar  # noqa: E402

HOJE = date(2026, 9, 24)


def documento(linhas_do_item: str, secao: str = "Abertas") -> str:
    return f"""# Pendências

## {secao}

### P-001 — alguma pergunta

| | |
|---|---|
| **Pergunta** | por quê? |
{linhas_do_item}

**O que ela bloqueia.** Alguma coisa.

## Candidatas

- nada
"""


def item(dono="Kawan", revisar="2026-10-08", revisoes="nenhuma"):
    return (
        f"| **Dono** | {dono} |\n"
        f"| **Revisar em** | {revisar} |\n"
        f"| **Estado** | aguardando |\n"
        f"| **Revisões** | {revisoes} |"
    )


def test_item_em_dia_passa():
    assert verificar(documento(item()), HOJE) == []


def test_prazo_vencido_falha():
    (falha,) = verificar(documento(item(revisar="2026-09-23")), HOJE)
    assert "vencida" in falha
    assert "2026-09-23" in falha


def test_prazo_hoje_ainda_passa():
    """Vence no fim do dia, não no começo."""
    assert verificar(documento(item(revisar="2026-09-24")), HOJE) == []


def test_sem_dono_falha():
    (falha,) = verificar(documento(item(dono="*a definir*")), HOJE)
    assert "sem dono" in falha


def test_dono_vazio_falha():
    (falha,) = verificar(documento(item(dono="")), HOJE)
    assert "sem dono" in falha


def test_data_ilegivel_falha():
    (falha,) = verificar(documento(item(revisar="semana que vem")), HOJE)
    assert "ilegivel" in falha


def test_renovacao_vira_carimbo_e_barrada():
    """O modo de falha da própria regra: renovar indefinidamente com a build
    verde e a pendência morta."""
    tres = "2026-09-10 sem resposta; 2026-09-17 sem resposta; 2026-09-24 sem resposta"
    falhas = verificar(documento(item(revisoes=tres)), HOJE)
    assert any("renovacoes sem mudar de estado" in f for f in falhas)


def test_duas_renovacoes_ainda_passam():
    duas = "2026-09-10 sem resposta; 2026-09-17 sem resposta"
    assert verificar(documento(item(revisoes=duas)), HOJE) == []


@pytest.mark.parametrize("secao", ["Fechadas", "Candidatas"])
def test_so_as_abertas_tem_prazo(secao):
    """Item fechado fica registrado para sempre; candidata não tem data."""
    assert verificar(documento(item(revisar="2020-01-01"), secao=secao), HOJE) == []


def test_arquivo_sem_pendencia_aberta_passa():
    assert verificar("# Pendências\n\n## Abertas\n\nNenhuma.\n", HOJE) == []


def test_o_arquivo_de_verdade_esta_em_dia():
    """O que o checador afirma, afirmado sobre este repositório."""
    texto = (RAIZ / ARQUIVO).read_text(encoding="utf-8")
    assert verificar(texto, date.today()) == []
    # Pelos IDs, e nao pela contagem: contagem continua certa se o leitor passar a
    # achar a pendencia errada no lugar da certa. Muda aqui quando uma pendencia
    # abre ou fecha — e deve mudar, porque isso e decisao, nao acidente.
    assert [item[0] for item in itens(texto)] == ["P-002"]


def test_limite_de_renovacoes_e_o_documentado():
    assert MAX_RENOVACOES == 3
