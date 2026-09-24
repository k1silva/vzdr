"""O checador que prova que não há atalho para o banco."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_dsn_guardada import PORTA_UNICA, verificar  # noqa: E402


def montar(tmp_path: Path, arquivos: dict) -> Path:
    for caminho, codigo in arquivos.items():
        destino = tmp_path / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(codigo, encoding="utf-8")
    return tmp_path


def test_conexao_direta_em_script_falha(tmp_path):
    raiz = montar(tmp_path, {"scripts/x.py": "import psycopg\npsycopg.connect('...')\n"})
    (falha,) = verificar(raiz)
    assert "scripts/x.py:2" in falha
    assert "conectar()" in falha


def test_connect_importado_direto_tambem_falha(tmp_path):
    raiz = montar(tmp_path, {"tests/db/y.py": "from psycopg import connect\nconnect('...')\n"})
    assert len(verificar(raiz)) == 1


def test_a_porta_unica_pode_conectar(tmp_path):
    raiz = montar(tmp_path, {PORTA_UNICA: "import psycopg\npsycopg.connect('...')\n"})
    assert verificar(raiz) == []


def test_chamar_conectar_passa(tmp_path):
    raiz = montar(
        tmp_path,
        {"scripts/x.py": "from scripts.ambiente_db import conectar\nconectar({})\n"},
    )
    assert verificar(raiz) == []


def test_arvore_sem_as_pastas_nao_quebra(tmp_path):
    assert verificar(tmp_path) == []


def test_o_repositorio_de_verdade_esta_conforme():
    """O que o checador afirma, afirmado sobre este repositório."""
    assert verificar(RAIZ) == []
