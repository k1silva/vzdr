#!/usr/bin/env python3
"""Falha o build se o fecho de 3.9 vazar.

O alvo de execucao 3.9 vale so para o que roda no hypervisor: `packages/agent` e o
fecho de dependencias dele. Um pacote restrito que importe um pacote sem a restricao
quebra no hypervisor em tempo de import, nao na CI — por isso o checador. Ver ADR-0007.

O conjunto de pacotes restritos nao e escrito aqui: sai de quem declara
`target-version = "py39"` no proprio pyproject.toml. Fonte unica.
"""

import ast
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PACOTES = RAIZ / "packages"

# Pacotes que rodam no hypervisor e, portanto, TEM que continuar restritos.
# Se alguem tirar o py39 do pyproject de um deles, isso aqui falha em vez de
# a restricao sumir em silencio.
OBRIGATORIOS = {"agent", "core-domain"}


def alvo_do_pacote(pasta: Path) -> str:
    """Le target-version do pyproject do pacote; '' quando nao declara."""
    arquivo = pasta / "pyproject.toml"
    if not arquivo.exists():
        return ""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    return str(dados.get("tool", {}).get("ruff", {}).get("target-version", ""))


def modulos_do_pacote(pasta: Path) -> list:
    """Modulos vzdr.* que o pacote fornece: pastas com __init__.py sob src/."""
    src = pasta / "src"
    if not src.exists():
        return []
    return [
        ".".join(d.relative_to(src).parts)
        for d in sorted(src.rglob("*"))
        if d.is_dir() and (d / "__init__.py").exists()
    ]


def imports_de(arquivo: Path):
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for a in no.names:
                yield no.lineno, a.name
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            yield no.lineno, no.module


def verificar(raiz: Path) -> list:
    """Devolve a lista de falhas. Recebe a raiz para ser testavel."""
    pacotes = raiz / "packages"
    if not pacotes.exists():
        return []

    pastas = sorted(p for p in pacotes.iterdir() if p.is_dir())
    restritos = {p.name for p in pastas if alvo_do_pacote(p) == "py39"}

    falhas = []

    faltando = OBRIGATORIOS - restritos
    for nome in sorted(faltando):
        falhas.append(
            f"packages/{nome}/pyproject.toml: roda no hypervisor e perdeu "
            f'target-version = "py39". Ver ADR-0007.'
        )

    # modulo vzdr.* -> pacote que o fornece
    dono = {}
    for pasta in pastas:
        for mod in modulos_do_pacote(pasta):
            dono[mod] = pasta.name

    for pasta in pastas:
        if pasta.name not in restritos or not (pasta / "src").exists():
            continue
        for arquivo in sorted((pasta / "src").rglob("*.py")):
            for linha, alvo in imports_de(arquivo):
                if not alvo.startswith("vzdr."):
                    continue
                # casa o prefixo mais longo: vzdr.core.domain.x -> vzdr.core.domain
                partes = alvo.split(".")
                provedor = ""
                for i in range(len(partes), 0, -1):
                    provedor = dono.get(".".join(partes[:i]), "")
                    if provedor:
                        break
                if provedor and provedor not in restritos:
                    falhas.append(
                        f"{arquivo.relative_to(raiz)}:{linha}: '{pasta.name}' roda no "
                        f"hypervisor (3.9) e importa '{alvo}', de '{provedor}', que nao "
                        f"tem a restricao. Ou o alvo entra no fecho, ou o import sai."
                    )

    return falhas


def main() -> int:
    if not PACOTES.exists():
        print("aviso: packages/ ainda nao existe, nada a checar")
        return 0

    falhas = verificar(RAIZ)
    if falhas:
        print("Fecho de 3.9 violado — o que roda no hypervisor so importa o que e 3.9:")
        for f in falhas:
            print("  " + f)
        return 1

    restritos = sorted(
        p.name for p in (RAIZ / "packages").iterdir() if p.is_dir() and alvo_do_pacote(p) == "py39"
    )
    print(f"fecho de 3.9 ok ({', '.join(restritos) or 'nenhum pacote restrito'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
