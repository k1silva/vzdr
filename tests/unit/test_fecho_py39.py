"""O que o job de 3.9 roda tem que sair do fecho, e nada pode sair dele em silencio."""

from pathlib import Path

from scripts.fecho_py39 import divergencias_de_lint, importados_junto, pacotes_sem_teste
from scripts.fecho_py39 import testes_do_fecho as derivar


def montar(tmp_path: Path, testes: dict[str, list[str]], lintados: list[str]) -> Path:
    """Um repositorio com um pacote restrito, um irrestrito, e os testes dados."""
    for nome, modulo, alvo in [
        ("core-domain", "vzdr.core.domain", "py39"),
        ("core-tenancy", "vzdr.core.tenancy", ""),
    ]:
        pasta = tmp_path / "packages" / nome
        ruff = f'\n[tool.ruff]\ntarget-version = "{alvo}"\n' if alvo else ""
        pasta.mkdir(parents=True)
        (pasta / "pyproject.toml").write_text(f'[project]\nname = "{nome}"\n{ruff}')
        destino = pasta / "src" / Path(*modulo.split("."))
        destino.mkdir(parents=True)
        (destino / "__init__.py").write_text("")
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True)
    for nome, imports in testes.items():
        (unit / nome).write_text("\n".join(imports) + "\n")
    entradas = ", ".join(f'"tests/unit/{n}" = "py39"' for n in lintados)
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.ruff]\nper-file-target-version = {{ {entradas} }}\n"
    )
    return tmp_path


DO_FECHO = ["from vzdr.core.domain import x"]
MISTO = ["from vzdr.core.domain import x", "from vzdr.core.tenancy import y"]
DE_FORA = ["from vzdr.core.tenancy import y"]


def test_so_o_teste_todo_do_fecho_roda_sob_3_9(tmp_path):
    raiz = montar(
        tmp_path,
        {"test_a.py": DO_FECHO, "test_b.py": MISTO, "test_c.py": DE_FORA},
        lintados=["test_a.py"],
    )
    selecionados, _ = derivar(raiz)
    assert selecionados == [Path("tests/unit/test_a.py")]


def test_o_misto_sai_com_motivo_e_nao_em_silencio(tmp_path):
    """Teste que deixa de rodar sem ninguem saber e verificacao que nao verifica."""
    raiz = montar(tmp_path, {"test_a.py": DO_FECHO, "test_b.py": MISTO}, lintados=["test_a.py"])
    _, excluidos = derivar(raiz)
    assert any("test_b.py" in e and "core-tenancy" in e for e in excluidos), excluidos


def test_teste_do_fecho_lintado_como_3_11_reprova(tmp_path):
    """O sentido que deixou o `datetime.UTC` chegar ao main."""
    raiz = montar(tmp_path, {"test_a.py": DO_FECHO}, lintados=[])
    selecionados, _ = derivar(raiz)
    divergencias = divergencias_de_lint(raiz, selecionados)
    assert any("test_a.py" in d and "acrescente" in d for d in divergencias), divergencias


def test_entrada_de_lint_sem_teste_do_fecho_reprova(tmp_path):
    """O outro sentido: a lista afirmando um teste do fecho que nao e."""
    raiz = montar(
        tmp_path, {"test_a.py": DO_FECHO, "test_c.py": DE_FORA}, lintados=["test_a.py", "test_c.py"]
    )
    selecionados, _ = derivar(raiz)
    divergencias = divergencias_de_lint(raiz, selecionados)
    assert any("test_c.py" in d and "retire" in d for d in divergencias), divergencias


def test_listas_iguais_nao_divergem(tmp_path):
    raiz = montar(tmp_path, {"test_a.py": DO_FECHO}, lintados=["test_a.py"])
    selecionados, _ = derivar(raiz)
    assert divergencias_de_lint(raiz, selecionados) == []


def _escrever(raiz: Path, caminho: str, texto: str = "") -> None:
    arquivo = raiz / caminho
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(texto)


def test_o_que_o_pytest_importa_junto_vai_junto(tmp_path):
    """conftest.py e __init__.py do caminho ate o teste: o 3.9 os importa de
    qualquer jeito. O conftest de outro diretorio, nao."""
    raiz = montar(tmp_path, {"test_a.py": DO_FECHO}, lintados=["test_a.py"])
    for caminho in [
        "conftest.py",
        "tests/__init__.py",
        "tests/conftest.py",
        "tests/unit/conftest.py",
        "tests/db/conftest.py",
    ]:
        _escrever(raiz, caminho)
    selecionados, _ = derivar(raiz)
    assert set(importados_junto(raiz, selecionados)) == {
        Path("conftest.py"),
        Path("tests/__init__.py"),
        Path("tests/conftest.py"),
        Path("tests/unit/conftest.py"),
    }


def test_auxiliar_importado_vai_junto_transitivamente(tmp_path):
    """Pelo teste e pelo conftest, absoluto e relativo, e o que o auxiliar importa."""
    raiz = montar(
        tmp_path,
        {"test_a.py": [*DO_FECHO, "from tests.unit.auxiliar import fabrica"]},
        lintados=["test_a.py"],
    )
    _escrever(raiz, "tests/__init__.py")
    _escrever(raiz, "tests/unit/__init__.py")
    _escrever(raiz, "tests/unit/auxiliar.py", "from .profundo import x\n")
    _escrever(raiz, "tests/unit/profundo.py")
    _escrever(raiz, "tests/unit/conftest.py", "from tests import apoio\n")
    _escrever(raiz, "tests/apoio.py")
    _escrever(raiz, "tests/unit/alheio.py")
    selecionados, _ = derivar(raiz)
    junto = set(importados_junto(raiz, selecionados))
    assert {
        Path("tests/unit/auxiliar.py"),
        Path("tests/unit/profundo.py"),
        Path("tests/apoio.py"),
    } <= junto
    assert Path("tests/unit/alheio.py") not in junto


def test_conftest_fora_do_lint_reprova(tmp_path):
    """A porta ao lado: o conftest e lintado como 3.11 e o `make fmt` escreve
    `datetime.UTC` nele."""
    raiz = montar(tmp_path, {"test_a.py": DO_FECHO}, lintados=["test_a.py"])
    _escrever(raiz, "tests/unit/conftest.py")
    selecionados, _ = derivar(raiz)
    divergencias = divergencias_de_lint(raiz, selecionados + importados_junto(raiz, selecionados))
    assert any("tests/unit/conftest.py" in d for d in divergencias), divergencias


def _segundo_restrito(raiz: Path) -> None:
    """O `agent`: restrito como o core-domain, e sem teste nenhum."""
    _escrever(raiz, "packages/agent/pyproject.toml", '[tool.ruff]\ntarget-version = "py39"\n')
    _escrever(raiz, "packages/agent/src/vzdr/agent/__init__.py")


def test_pacote_restrito_sem_teste_aparece(tmp_path):
    """ "N aprovados sob 3.9" nao pode esconder que metade do fecho nao executa nada."""
    raiz = montar(tmp_path, {"test_a.py": DO_FECHO}, lintados=["test_a.py"])
    _segundo_restrito(raiz)
    selecionados, _ = derivar(raiz)
    assert pacotes_sem_teste(raiz, selecionados) == ["agent"]


def test_pacote_restrito_com_teste_nao_aparece(tmp_path):
    raiz = montar(
        tmp_path,
        {"test_a.py": DO_FECHO, "test_b.py": ["from vzdr.agent import z"]},
        lintados=["test_a.py", "test_b.py"],
    )
    _segundo_restrito(raiz)
    selecionados, _ = derivar(raiz)
    assert pacotes_sem_teste(raiz, selecionados) == []


def test_import_so_de_teste_misto_nao_cobre(tmp_path):
    """O misto nao roda sob 3.9, entao o que ele importa continua sem teste."""
    raiz = montar(
        tmp_path,
        {"test_b.py": ["from vzdr.agent import z", "from vzdr.core.tenancy import y"]},
        lintados=[],
    )
    _segundo_restrito(raiz)
    _escrever(raiz, "tests/unit/test_a.py", "from vzdr.core.domain import x\n")
    selecionados, _ = derivar(raiz)
    assert pacotes_sem_teste(raiz, selecionados) == ["agent"]
