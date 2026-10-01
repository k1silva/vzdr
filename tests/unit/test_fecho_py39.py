"""O que o job de 3.9 roda tem que sair do fecho, e nada pode sair dele em silencio."""

from pathlib import Path

from scripts.fecho_py39 import divergencias_de_lint
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
