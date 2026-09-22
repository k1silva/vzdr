"""O checador do fecho de 3.9 precisa pegar as tres formas de vazamento."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_alvo_py39 import verificar  # noqa: E402


def montar(tmp_path: Path, pacotes: dict) -> Path:
    """pacotes: {nome: {"alvo": "py39"|"", "modulos": {"vzdr.x": ["import ..."]}}}"""
    for nome, cfg in pacotes.items():
        pasta = tmp_path / "packages" / nome
        pasta.mkdir(parents=True)
        alvo = cfg.get("alvo", "")
        ruff = f'\n[tool.ruff]\ntarget-version = "{alvo}"\n' if alvo else ""
        (pasta / "pyproject.toml").write_text(f'[project]\nname = "{nome}"\n{ruff}')
        for modulo, linhas in cfg.get("modulos", {}).items():
            destino = pasta / "src" / Path(*modulo.split("."))
            destino.mkdir(parents=True)
            (destino / "__init__.py").write_text("")
            (destino / "codigo.py").write_text("\n".join(linhas) + "\n")
    return tmp_path


def test_pacote_restrito_importando_irrestrito_falha(tmp_path):
    raiz = montar(
        tmp_path,
        {
            "agent": {
                "alvo": "py39",
                "modulos": {"vzdr.agent": ["from vzdr.core.tenancy import autenticar"]},
            },
            "core-domain": {"alvo": "py39", "modulos": {"vzdr.core.domain": []}},
            "core-tenancy": {"alvo": "", "modulos": {"vzdr.core.tenancy": []}},
        },
    )
    falhas = verificar(raiz)
    assert len(falhas) == 1
    assert "vzdr.core.tenancy" in falhas[0]
    assert "core-tenancy" in falhas[0]


def test_pacote_restrito_importando_restrito_passa(tmp_path):
    raiz = montar(
        tmp_path,
        {
            "agent": {
                "alvo": "py39",
                "modulos": {"vzdr.agent": ["from vzdr.core.domain import Principal"]},
            },
            "core-domain": {"alvo": "py39", "modulos": {"vzdr.core.domain": []}},
        },
    )
    assert verificar(raiz) == []


def test_perder_a_restricao_falha(tmp_path):
    """Tirar py39 do agent nao pode passar em silencio."""
    raiz = montar(
        tmp_path,
        {
            "agent": {"alvo": "py311", "modulos": {"vzdr.agent": []}},
            "core-domain": {"alvo": "py39", "modulos": {"vzdr.core.domain": []}},
        },
    )
    falhas = verificar(raiz)
    assert len(falhas) == 1
    assert "agent" in falhas[0] and "ADR-0007" in falhas[0]


def test_import_de_terceiro_e_ignorado(tmp_path):
    """A invariante e sobre o fecho vzdr.*; stdlib e terceiro nao entram aqui."""
    raiz = montar(
        tmp_path,
        {
            "agent": {"alvo": "py39", "modulos": {"vzdr.agent": ["import json", "import libvirt"]}},
            "core-domain": {"alvo": "py39", "modulos": {"vzdr.core.domain": []}},
        },
    )
    assert verificar(raiz) == []


def test_packages_ausente_nao_quebra(tmp_path):
    assert verificar(tmp_path) == []
