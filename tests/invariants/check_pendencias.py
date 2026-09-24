#!/usr/bin/env python3
"""Falha o build quando uma pendencia passou da data de revisao.

`docs/pendencias.md` diz que nao existe "continua pendente" em silencio. Sem
alguem fazendo cumprir, essa frase depende de alguem abrir o arquivo — que e
exatamente o problema que o arquivo existe para resolver, um nivel acima.

Este checador e diferente dos outros deste repositorio, e vale saber por que:
os demais falham por causa do que voce mudou; este falha por causa do tempo
passar. Ele vai quebrar a build de quem estava mexendo em outra coisa. E
deliberado. A alternativa — avisar sem bloquear — e o que este projeto ja
decidiu, repetidas vezes, que ninguem le.

O conserto e legitimo e leva trinta segundos: ou o item muda de estado, ou a
data muda com motivo escrito.

## O limite de renovacoes

O modo de falha desta regra nao e ela bloquear: e a renovacao virar carimbo.
"+2 semanas, sem resposta ainda", indefinidamente, com a build verde e a
pendencia morta — a mesma forma de "verificacao que nao verifica" que este
repositorio ja levou cinco vezes. Por isso a terceira renovacao falha tambem, e
so sai com mudanca de estado.
"""

import re
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = "docs/pendencias.md"

MAX_RENOVACOES = 3

# `### P-001 — titulo` ate o proximo cabecalho de mesmo nivel ou maior.
ITEM = re.compile(r"^### (P-\d+)\s+—\s+(.+?)$", re.MULTILINE)
CAMPO = re.compile(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.*?)\s*\|\s*$", re.MULTILINE)


def _secao_abertas(texto: str) -> str:
    """So as pendencias abertas. Fechadas e candidatas nao tem prazo."""
    if "\n## Abertas" not in texto:
        return ""
    depois = texto.split("\n## Abertas", 1)[1]
    return depois.split("\n## ", 1)[0]


def itens(texto: str) -> list:
    """(id, titulo, campos) de cada pendencia aberta."""
    secao = _secao_abertas(texto)
    achados = []
    marcas = list(ITEM.finditer(secao))
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(secao)
        corpo = secao[m.start() : fim]
        campos = {k.strip(): v.strip() for k, v in CAMPO.findall(corpo)}
        achados.append((m.group(1), m.group(2), campos))
    return achados


def _renovacoes(valor: str) -> int:
    if not valor or valor.lower().startswith("nenhuma"):
        return 0
    # Cada renovacao e uma data no texto da celula.
    return len(re.findall(r"\d{4}-\d{2}-\d{2}", valor))


def verificar(texto: str, hoje: date) -> list:
    falhas = []
    achados = itens(texto)
    if not achados:
        return falhas

    for ident, titulo, campos in achados:
        rotulo = f"{ident} ({titulo})"

        dono = campos.get("Dono", "")
        if not dono or "a definir" in dono.lower():
            falhas.append(
                f"{rotulo}: sem dono.\n"
                f"      Pendencia sem dono e a suposicao de que alguem vai lembrar."
            )

        bruto = campos.get("Revisar em", "")
        try:
            prazo = date.fromisoformat(bruto)
        except ValueError:
            falhas.append(
                f"{rotulo}: 'Revisar em' ausente ou ilegivel ({bruto!r}).\n"
                f"      Use AAAA-MM-DD. Pendencia sem data de revisao e esquecimento "
                f"com boa intencao."
            )
            continue

        if prazo < hoje:
            falhas.append(
                f"{rotulo}: revisao vencida em {prazo} (hoje e {hoje}).\n"
                f"      Mude o estado, ou mude a data com o motivo na linha 'Revisoes'.\n"
                f"      Nao existe 'continua pendente' em silencio."
            )

        renovacoes = _renovacoes(campos.get("Revisões", campos.get("Revisoes", "")))
        if renovacoes >= MAX_RENOVACOES:
            falhas.append(
                f"{rotulo}: {renovacoes} renovacoes sem mudar de estado.\n"
                f"      Renovar e barato uma vez; na {MAX_RENOVACOES}a a pendencia nao "
                f"esta sendo tocada.\n"
                f"      Escale, feche, ou mova para 'Candidatas' — mas nao renove de novo."
            )

    return falhas


def main() -> int:
    caminho = RAIZ / ARQUIVO
    if not caminho.exists():
        print(f"aviso: {ARQUIVO} nao existe, nada a checar")
        return 0

    texto = caminho.read_text(encoding="utf-8")
    falhas = verificar(texto, date.today())
    if falhas:
        print(f"Pendencias fora do prazo em {ARQUIVO}:")
        for f in falhas:
            print("  " + f)
        return 1

    abertas = len(itens(texto))
    print(f"pendencias em dia ({abertas} aberta(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
