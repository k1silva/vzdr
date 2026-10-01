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


def testes_lintados_como_py39(raiz: Path) -> set[Path]:
    dados = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))
    por_arquivo = dados.get("tool", {}).get("ruff", {}).get("per-file-target-version", {})
    return {Path(caminho) for caminho, alvo in por_arquivo.items() if alvo == "py39"}


def divergencias_de_lint(raiz: Path, selecionados: list[Path]) -> list[str]:
    """O que separa a lista do ruff da derivada, nos dois sentidos."""
    lintados = testes_lintados_como_py39(raiz)
    return [
        f"{t}: roda sob 3.9 e o ruff o linta como 3.11 — acrescente ao "
        f"per-file-target-version do pyproject.toml"
        for t in sorted(set(selecionados) - lintados)
    ] + [
        f"{t}: esta no per-file-target-version e nao e teste do fecho — retire"
        for t in sorted(lintados - set(selecionados))
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
        divergencias = divergencias_de_lint(RAIZ, selecionados)
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
