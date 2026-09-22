#!/usr/bin/env python3
"""Falha o build se uma migracao criar tabela de dado de tenant sem tenant_id.

P9, na forma que vale: *toda tabela que guarda dado de tenant* tem `tenant_id`,
desde a primeira migracao. Escrita como "toda tabela, sem excecao", a invariante
seria falsa no proprio desenho da core-001 — e invariante falsa e pior que
invariante ausente, porque o checador vira ruido que alguem aprende a silenciar.

A lista de excecoes e FECHADA e vive em specs/core-001-tenancy/spec.md. O mapa
abaixo a espelha, com a justificativa de cada uma; um teste falha se as duas
divergirem. Acrescentar entrada aqui sem alterar a spec e violacao de P9, nao
configuracao.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SPEC = "specs/core-001-tenancy/spec.md"


@dataclass(frozen=True)
class Isencao:
    porque: str
    # False so para tabela que nenhuma migracao cria; ver schema_migrations.
    criada_por_migracao: bool = True


ISENTAS = {
    "tenants": Isencao("e o proprio eixo de tenant"),
    "usuarios": Isencao(
        "o vinculo com tenant vive em associacao_tenant, que pode ter mais de uma linha por usuario"
    ),
    "papel_plataforma": Isencao(
        "existe fora do eixo; papel de plataforma com tenant seria um tenant privilegiado"
    ),
    "auditoria_plataforma": Isencao("registra atos que nao acontecem dentro de tenant nenhum"),
    "sessao_plataforma": Isencao("sessao do papel de plataforma, que nao tem tenant ativo"),
    "schema_migrations": Isencao(
        "metadado do executor de migracao, criado por scripts/migrar.py",
        criada_por_migracao=False,
    ),
}

PADRAO = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?([\w.\"]+)(.*?);",
    re.IGNORECASE | re.DOTALL,
)


def criacoes_em(pasta: Path) -> list[tuple[str, str, str]]:
    """(arquivo, tabela, corpo) de cada create table, em ordem de arquivo."""
    achados = []
    for arquivo in sorted(pasta.rglob("*.sql")):
        texto = arquivo.read_text(encoding="utf-8")
        for m in PADRAO.finditer(texto):
            # Separa o nome qualificado ANTES de tirar as aspas: o contrario
            # deixa '"public"."vm"' virar '"vm' e a tabela nao casa com a isencao.
            nome = m.group(1).split(".")[-1].strip('"').lower()
            achados.append((arquivo.name, nome, m.group(2)))
    return achados


def verificar(raiz: Path) -> list[str]:
    """Devolve a lista de falhas. Recebe a raiz para ser testavel."""
    pasta = raiz / "deploy" / "migrations"
    if not pasta.exists():
        return []

    criacoes = criacoes_em(pasta)
    if not criacoes:
        # Nenhuma migracao ainda: nao ha o que checar, e toda excecao pareceria
        # morta. Ver a checagem de excecao morta abaixo.
        return []

    falhas = []
    usadas = set()

    for arquivo, tabela, corpo in criacoes:
        if tabela in ISENTAS:
            usadas.add(tabela)
            continue
        if "tenant_id" not in corpo.lower():
            falhas.append(
                f"{arquivo}: tabela '{tabela}' sem tenant_id.\n"
                f"      Se guarda dado de tenant, acrescente a coluna.\n"
                f"      Se nao guarda, a excecao entra em {SPEC} primeiro, com"
                f" justificativa — nao aqui."
            )

    for tabela, isencao in sorted(ISENTAS.items()):
        if not isencao.criada_por_migracao or tabela in usadas:
            continue
        falhas.append(
            f"excecao morta: '{tabela}' esta isenta ({isencao.porque}) e nenhuma"
            f" migracao a cria.\n"
            f"      Excecao que ninguem usa e excecao que alguem herda sem saber"
            f" por que.\n"
            f"      Remova daqui e de {SPEC}."
        )

    return falhas


def main() -> int:
    pasta = RAIZ / "deploy" / "migrations"
    if not pasta.exists():
        print(f"aviso: {pasta} ainda nao existe, nada a checar")
        return 0

    falhas = verificar(RAIZ)
    if falhas:
        print("P9 violado — tenant_id em toda tabela que guarda dado de tenant:")
        for f in falhas:
            print("  " + f)
        print(f"\n  A lista fechada de excecoes esta em {SPEC}.")
        return 1

    criacoes = criacoes_em(pasta)
    if not criacoes:
        print("nenhuma migracao ainda, nada a checar")
        return 0

    print(
        f"tenant_id ok: {len(criacoes)} tabela(s), "
        f"{len({t for _, t, _ in criacoes} & set(ISENTAS))} isenta(s) pela spec"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
