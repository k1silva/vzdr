#!/usr/bin/env python3
"""Falha o build se o fecho de 3.9 vazar.

O alvo de execucao 3.9 vale so para o que roda no hypervisor: `packages/agent` e o
fecho de dependencias dele. Um pacote restrito que importe um pacote sem a restricao
quebra no hypervisor em tempo de import, nao na CI — por isso o checador. Ver ADR-0007.

O conjunto de pacotes restritos nao e escrito aqui: sai de quem declara
`target-version = "py39"` no proprio pyproject.toml. Fonte unica.

## Duas regras, e a segunda nao e sobre sintaxe

1. **Fecho de import**: pacote restrito so importa pacote restrito.
2. **Terceiros**: pacote restrito so importa a biblioteca padrao e `vzdr.*`.

A segunda existe porque o fecho de 3.9 nao e so questao de sintaxe — e o que
consegue ser **instalado no hypervisor**. Dependencia com extensao C que entra
no agente e problema que aparece no dia do deploy, no host do cliente, e nao na
CI.

`TERCEIROS_PERMITIDOS` tem hoje um nome so: `libvirt`, que vem da distribuicao
no hypervisor e e a razao de o agente rodar la. Cada entrada e uma coisa que
precisa existir no host do CLIENTE, entao acrescentar uma e decisao de deploy,
com justificativa — e `cryptography`, que entra em `core-connections` na
core-002, **nao pode** chegar aqui.
"""

import ast
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PACOTES = RAIZ / "packages"

#: Terceiros que o codigo do hypervisor pode importar, com justificativa.
#: Nao e lista de conveniencia: cada nome aqui e uma coisa que precisa existir
#: no host do cliente, e acrescentar um e decisao de deploy.
TERCEIROS_PERMITIDOS = {
    # Binding Python do libvirt. Vem da distribuicao no hypervisor, e e a razao
    # de o agente rodar la — sem ele nao ha o que fazer.
    "libvirt",
}

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
                topo = alvo.split(".")[0]
                if not alvo.startswith("vzdr."):
                    if topo not in sys.stdlib_module_names and topo not in TERCEIROS_PERMITIDOS:
                        falhas.append(
                            f"{arquivo.relative_to(raiz)}:{linha}: '{pasta.name}' roda no "
                            f"hypervisor e importa '{alvo}', que nao e da biblioteca "
                            f"padrao.\n"
                            f"      Extensao C no agente aparece no dia do deploy, no "
                            f"host do cliente, e nao na CI.\n"
                            f"      Se for mesmo necessaria, acrescente a "
                            f"TERCEIROS_PERMITIDOS com justificativa."
                        )
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
