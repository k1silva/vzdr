"""O que o job de 3.9 instala e o que ele roda — derivado, nunca listado.

O `check_alvo_py39.py` verifica o fecho por PROCURACAO: le `target-version` e os
imports. O job `alvo-py39` so compilava. Nenhum dos dois EXECUTA nada sob 3.9, e
a classe que escapa e a de chamada 3.10+ com sintaxe valida: `zip(..., strict=True)`
compila em 3.9 e quebra ao rodar. O hypervisor nao compila — executa.

Este script responde as duas perguntas do `make test-py39`, a partir da mesma
fonte unica do checador (quem declara `target-version = "py39"`):

- `pacotes`: as pastas dos pacotes restritos, para instalar;
- `testes`: os testes de `tests/unit` cujos imports de `vzdr.*` sao TODOS de
  pacotes restritos. Teste MISTO — que importa do fecho e de fora dele — nao pode
  rodar sob 3.9, e sai impresso no erro padrao com o motivo, em vez de sumir: um
  teste que deixa de rodar em silencio e verificacao que nao verifica. Lista vazia
  e erro, pelo mesmo motivo.

E os testes selecionados sao conferidos contra o `per-file-target-version` do
pyproject da raiz, nos dois sentidos. Teste do fecho fora dele seria lintado como
3.11 — e o `make fmt` reescreve `timezone.utc` em `datetime.UTC` sozinho, que foi
como o primeiro caso chegou ao `main`. Entrada sem teste e lista mentindo.
"""

import ast
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_alvo_py39 import alvo_do_pacote, imports_de, modulos_do_pacote  # noqa: E402


def pacotes_restritos(raiz: Path) -> list[Path]:
    return sorted(
        p for p in (raiz / "packages").iterdir() if p.is_dir() and alvo_do_pacote(p) == "py39"
    )


def _provedor(modulo: str, dono: dict[str, str]) -> str:
    """O pacote que fornece o modulo, pelo prefixo mais longo."""
    partes = modulo.split(".")
    for i in range(len(partes), 0, -1):
        achado = dono.get(".".join(partes[:i]))
        if achado:
            return achado
    return ""


def testes_do_fecho(raiz: Path) -> tuple[list[Path], list[str]]:
    """(testes que rodam sob 3.9, motivos dos mistos excluidos)."""
    restritos = {p.name for p in pacotes_restritos(raiz)}
    dono = {
        mod: pasta.name
        for pasta in sorted((raiz / "packages").iterdir())
        if pasta.is_dir()
        for mod in modulos_do_pacote(pasta)
    }
    selecionados, excluidos = [], []
    for arquivo in sorted((raiz / "tests" / "unit").glob("test_*.py")):
        provedores = {
            _provedor(alvo, dono) for _, alvo in imports_de(arquivo) if alvo.startswith("vzdr.")
        }
        if not provedores & restritos:
            continue
        de_fora = sorted(provedores - restritos)
        if de_fora:
            excluidos.append(
                f"{arquivo.relative_to(raiz)}: importa do fecho e de {', '.join(de_fora)}"
            )
        else:
            selecionados.append(arquivo.relative_to(raiz))
    return selecionados, excluidos


def _modulo_local(raiz: Path, nome: str) -> Path | None:
    """O arquivo do repositorio que o nome pontilhado importa, se for local."""
    base = raiz / Path(*nome.split("."))
    for candidato in (base.with_suffix(".py"), base / "__init__.py"):
        if candidato.is_file():
            return candidato
    return None


def _imports_locais(raiz: Path, arquivo: Path) -> set[Path]:
    """Os arquivos do repositorio que `arquivo` importa: absolutos (`tests.x`) e
    relativos. Em `from a import b`, `b` pode ser submodulo, e entao conta tambem."""
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    pacote = arquivo.parent.relative_to(raiz).parts
    nomes: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes += [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom):
            prefixo = list(pacote[: len(pacote) - no.level + 1]) if no.level else []
            modulo = ".".join(prefixo + ([no.module] if no.module else []))
            nomes += [modulo] + [f"{modulo}.{a.name}" if modulo else a.name for a in no.names]
    achados = {_modulo_local(raiz, n) for n in nomes if n and not n.startswith("vzdr.")}
    return {a for a in achados if a is not None and a.is_relative_to(raiz / "tests")}


def importados_junto(raiz: Path, selecionados: list[Path]) -> list[Path]:
    """O que o pytest importa ao coletar os testes do fecho, alem deles mesmos.

    `conftest.py` e `__init__.py` de cada diretorio entre a raiz e o teste — o
    pytest os importa de qualquer jeito —, e todo modulo local que algum deles
    importe, transitivamente. Sob 3.9 sao importados como os testes; fora da lista
    do ruff seriam lintados como 3.11, e o `make fmt` escreveria `datetime.UTC`
    neles pela porta ao lado da que ja foi fechada.
    """
    pendentes: list[Path] = []
    for teste in selecionados:
        pasta = (raiz / teste).parent
        while pasta.is_relative_to(raiz):
            pendentes += [pasta / n for n in ("conftest.py", "__init__.py")]
            if pasta == raiz:
                break
            pasta = pasta.parent
        pendentes.append(raiz / teste)
    vistos: set[Path] = set()
    while pendentes:
        arquivo = pendentes.pop()
        if arquivo in vistos or not arquivo.is_file():
            continue
        vistos.add(arquivo)
        pendentes += _imports_locais(raiz, arquivo)
    testes = {raiz / t for t in selecionados}
    return sorted(a.relative_to(raiz) for a in vistos - testes)


def testes_lintados_como_py39(raiz: Path) -> set[Path]:
    dados = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))
    por_arquivo = dados.get("tool", {}).get("ruff", {}).get("per-file-target-version", {})
    return {Path(caminho) for caminho, alvo in por_arquivo.items() if alvo == "py39"}


def divergencias_de_lint(raiz: Path, sob_3_9: list[Path]) -> list[str]:
    """O que separa a lista do ruff da derivada, nos dois sentidos. `sob_3_9` e
    tudo o que o 3.9 importa: os testes e o que vem junto com eles."""
    lintados = testes_lintados_como_py39(raiz)
    return [
        f"{t}: e importado sob 3.9 e o ruff o linta como 3.11 — acrescente ao "
        f"per-file-target-version do pyproject.toml"
        for t in sorted(set(sob_3_9) - lintados)
    ] + [
        f"{t}: esta no per-file-target-version e o 3.9 nao o importa — retire"
        for t in sorted(lintados - set(sob_3_9))
    ]


def main(argv: list[str]) -> int:
    pergunta = argv[1] if len(argv) == 2 else ""
    if pergunta == "pacotes":
        for p in pacotes_restritos(RAIZ):
            print(p.relative_to(RAIZ))
        return 0
    if pergunta == "testes":
        selecionados, excluidos = testes_do_fecho(RAIZ)
        for motivo in excluidos:
            print(f"fora do 3.9 (misto): {motivo}", file=sys.stderr)
        if not selecionados:
            print("nenhum teste exercita o fecho de 3.9", file=sys.stderr)
            return 1
        junto = importados_junto(RAIZ, selecionados)
        divergencias = divergencias_de_lint(RAIZ, selecionados + junto)
        for d in divergencias:
            print(d, file=sys.stderr)
        if divergencias:
            return 1
        for t in selecionados:
            print(t)
        return 0
    print("uso: fecho_py39.py pacotes|testes", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
