#!/usr/bin/env python3
"""Afirmacao de desenho nomeia o mecanismo que a mantem verdadeira — e a volta.

E o meta-checador bidirecional de coerencia documento <-> realidade. Tres regras:

1. **Toda afirmacao coberta nomeia um mecanismo.** Afirmacao e, por ESTRUTURA:
   cada linha da tabela `## Riscos` de um plano ("este risco e contido por isto"),
   e cada propriedade `### N.` sob `## Decisao` de um ADR, que declara o seu
   numa linha `**Mecanismo:**`.
2. **Todo mecanismo nomeado existe.** Referencia em crase, de quatro formas:
   - `tests/.../x.py::test_nome` — o arquivo existe e define a funcao;
   - `tests/invariants/check_x.py` (ou outro .py) — o arquivo existe;
   - `M4` — a medicao existe na tabela do ADR-0012;
   - `T7` — a tarefa existe e AINDA ESTA ABERTA. E declaracao honesta de que o
     mecanismo ainda nao existe. Tarefa marcada feita com a afirmacao ainda
     apontando para ela reprova: o mecanismo tinha que ter sido nomeado.
3. **A volta, que e a metade que se esquece: todo checador no build e
   reivindicado.** Por uma referencia num documento coberto, ou pelo nome do
   arquivo, em crase, no AGENTS.md. Sem isto acumulam checadores orfaos, e o
   primeiro que der trabalho sera apagado sem que se saiba o que se apagou.

ESCOPO POR DOCUMENTO, NUNCA PELO CRITERIO. Enfraquecer o criterio para terminar
rapido seria contorno disfarcado: a regra continuaria escrita e deixaria de
morder. Limitar quais documentos ele cobre e honesto e visivel — a lista do que
falta e impressa em toda execucao.

PREVISAO, REGISTRADA ANTES DA PRIMEIRA EXECUCAO SOBRE O REPOSITORIO. Os cinco
checadores anteriores nasceram vermelhos num achado real, e este tem que nascer
vermelho tambem; se nascer verde, a conclusao nao e "as specs estao perfeitas", e
"o criterio esta fraco". A previsao:

- vermelho na regra 1 em linhas de `## Riscos` do plano da dr-001: a coluna de
  mitigacao foi escrita em prosa, e varias linhas citam um documento ou uma
  intencao ("e o ADR-0015", "o plano ja diz") em vez de um mecanismo;
- vermelho na regra 1 nas quatro propriedades do ADR-0015, que nao declaram
  mecanismo nenhum;
- vermelho na regra 3 nos checadores que o AGENTS.md reivindica so em prosa — a
  secao "Fronteiras — a CI verifica" diz o que e verificado sem nomear quem
  verifica.
"""

import re
import sys
from pathlib import Path

from blocos_markdown import linhas_fora_de_blocos

RAIZ = Path(__file__).resolve().parents[2]

#: Documentos cobertos. Cresce por documento, e nunca afrouxando o criterio.
COBERTOS_PLANO = ("specs/dr-001-dominio-ciclo/plan.md",)
COBERTOS_ADR = ("docs/adr/0015-efeito-como-valor.md",)

#: O que ainda nao e coberto — impresso em toda execucao, para que a falta seja
#: visivel e nao presumida. Cada item sai daqui quando passa a ser coberto.
AINDA_NAO_COBERTOS = (
    "specs/core-001-tenancy/plan.md",
    "specs/core-002-connections/plan.md",
    "docs/adr/0005 a 0014 (os ADRs que o plano da dr-001 cita, e os demais)",
    "specs/*/spec.md (afirmacoes em prosa; sem forma estrutural ainda)",
)

TAREFAS = {"specs/dr-001-dominio-ciclo/plan.md": "specs/dr-001-dominio-ciclo/tasks.md"}
MEDICOES = "docs/adr/0012-resposta-a-perda-de-bitmap.md"

_CRASE = re.compile(r"`([^`]+)`")
_TESTE = re.compile(r"(?P<arquivo>(?:tests|scripts|packages)/[\w/.-]+\.py)::(?P<funcao>test_\w+)")
_ARQUIVO = re.compile(r"(?:tests|scripts|packages)/[\w/.-]+\.py")
_MEDICAO = re.compile(r"M\d+")
_TAREFA = re.compile(r"T\d+")
#: `dr-001/T6` — tarefa com a spec dita. Obrigatoria fora de um plano: num ADR, `T6`
#: solto nao diz de qual spec e a tarefa.
_TAREFA_QUALIFICADA = re.compile(r"(?P<spec>[a-z]+-\d+)/(?P<tarefa>T\d+)")
_CHECADOR_NO_MAKEFILE = re.compile(r"tests/invariants/(check_\w+\.py)")


def referencias(texto: str) -> list[str]:
    """As referencias a mecanismo num trecho — so as que tem forma de mecanismo."""
    achadas = []
    for item in _CRASE.findall(texto):
        item = item.strip()
        if (
            _TESTE.fullmatch(item)
            or _ARQUIVO.fullmatch(item)
            or _MEDICAO.fullmatch(item)
            or _TAREFA.fullmatch(item)
            or _TAREFA_QUALIFICADA.fullmatch(item)
        ):
            achadas.append(item)
    return achadas


def afirmacoes_do_plano(texto: str) -> list[tuple[str, list[str]]]:
    """(rotulo, referencias) de cada linha da tabela `## Riscos`."""
    dentro = False
    saida = []
    for _, linha in linhas_fora_de_blocos(texto):
        if linha.startswith("## "):
            dentro = linha.strip() == "## Riscos"
            continue
        if not dentro or not linha.startswith("|"):
            continue
        celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
        if len(celulas) < 2 or set(celulas[0]) <= set("-: ") or celulas[0] == "Risco":
            continue
        saida.append((celulas[0], referencias(" | ".join(celulas[1:]))))
    return saida


def afirmacoes_do_adr(texto: str) -> list[tuple[str, list[str]]]:
    """(rotulo, referencias) de cada `### N.` sob `## Decisao`."""
    secao = None
    atual: str | None = None
    refs: dict[str, list[str]] = {}
    ordem: list[str] = []
    for _, linha in linhas_fora_de_blocos(texto):
        if linha.startswith("## "):
            secao = linha.strip()
            atual = None
            continue
        if secao not in ("## Decisão", "## Decisao"):
            continue
        casou = re.match(r"### (\d+)\. (.*)", linha)
        if casou:
            atual = f"propriedade {casou.group(1)}: {casou.group(2).strip()}"
            refs[atual] = []
            ordem.append(atual)
            continue
        if atual and linha.startswith("**Mecanismo:**"):
            refs[atual].extend(referencias(linha))
    return [(r, refs[r]) for r in ordem]


def _medicoes(raiz: Path) -> set[str]:
    caminho = raiz / MEDICOES
    if not caminho.exists():
        return set()
    return set(re.findall(r"^\| (M\d+) \|", caminho.read_text(encoding="utf-8"), re.MULTILINE))


def _tarefas(raiz: Path, documento: str) -> dict[str, bool]:
    """T<n> -> feita? — das tarefas do proprio plano."""
    tasks = TAREFAS.get(documento)
    if tasks is None or not (raiz / tasks).exists():
        return {}
    return _tarefas_de(raiz / tasks)


def _tarefas_de(caminho: Path) -> dict[str, bool]:
    texto = caminho.read_text(encoding="utf-8")
    return {
        m.group(2): m.group(1).lower() == "x"
        for m in re.finditer(r"^- \[( |x|X)\] \*\*(T\d+)\*\*", texto, re.MULTILINE)
    }


def _problema_da_referencia(
    raiz: Path, ref: str, tarefas: dict[str, bool], medicoes: set[str]
) -> str | None:
    teste = _TESTE.fullmatch(ref)
    if teste:
        arquivo = raiz / teste.group("arquivo")
        if not arquivo.exists():
            return f"`{ref}`: o arquivo nao existe"
        if not re.search(
            r"^def " + teste.group("funcao") + r"\(",
            arquivo.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            return f"`{ref}`: a funcao nao existe no arquivo"
        return None
    if _ARQUIVO.fullmatch(ref):
        return None if (raiz / ref).exists() else f"`{ref}`: o arquivo nao existe"
    if _MEDICAO.fullmatch(ref):
        return None if ref in medicoes else f"`{ref}`: a medicao nao existe no ADR-0012"
    qualificada = _TAREFA_QUALIFICADA.fullmatch(ref)
    if qualificada:
        candidatos = sorted(raiz.glob(f"specs/{qualificada.group('spec')}-*/tasks.md"))
        if len(candidatos) != 1:
            return f"`{ref}`: a spec {qualificada.group('spec')} nao tem tasks.md unico"
        return _problema_da_referencia(
            raiz, qualificada.group("tarefa"), _tarefas_de(candidatos[0]), medicoes
        )
    if _TAREFA.fullmatch(ref):
        if not tarefas:
            return f"`{ref}`: tarefa sem spec — fora de um plano, escreva `spec/{ref}`"
        if ref not in tarefas:
            return f"`{ref}`: a tarefa nao existe"
        if tarefas[ref]:
            return f"`{ref}`: a tarefa esta feita, e a afirmacao ainda aponta para ela e nao para o mecanismo"
        return None
    return f"`{ref}`: forma de referencia desconhecida"


def verificar(raiz: Path) -> list[str]:
    falhas = []
    medicoes = _medicoes(raiz)
    reivindicados: set[str] = set()

    cobertos = [(d, afirmacoes_do_plano) for d in COBERTOS_PLANO] + [
        (d, afirmacoes_do_adr) for d in COBERTOS_ADR
    ]
    for documento, extrair in cobertos:
        caminho = raiz / documento
        if not caminho.exists():
            falhas.append(f"{documento}: documento coberto nao existe")
            continue
        tarefas = _tarefas(raiz, documento)
        afirmacoes = extrair(caminho.read_text(encoding="utf-8"))
        if not afirmacoes:
            falhas.append(f"{documento}: nenhuma afirmacao encontrada — a estrutura mudou?")
        for rotulo, refs in afirmacoes:
            if not refs:
                falhas.append(f"{documento}: '{rotulo}' nao nomeia mecanismo")
            for ref in refs:
                problema = _problema_da_referencia(raiz, ref, tarefas, medicoes)
                if problema:
                    falhas.append(f"{documento}: '{rotulo}': {problema}")
                if _ARQUIVO.fullmatch(ref):
                    reivindicados.add(Path(ref).name)
                elif _TESTE.fullmatch(ref):
                    reivindicados.add(Path(ref.split("::")[0]).name)

    agents = raiz / "AGENTS.md"
    if agents.exists():
        # LINHA A LINHA, e fora de bloco de codigo. A primeira versao pareava as
        # crases no arquivo inteiro de uma vez, e cada cerca de tres crases
        # deslocava o pareamento de todas as seguintes: na primeira execucao,
        # tres checadores nomeados em crase no AGENTS.md sairam como orfaos.
        for _, linha in linhas_fora_de_blocos(agents.read_text(encoding="utf-8")):
            for item in _CRASE.findall(linha):
                reivindicados.add(Path(item.strip()).name)

    makefile = raiz / "Makefile"
    no_build = (
        set(_CHECADOR_NO_MAKEFILE.findall(makefile.read_text(encoding="utf-8")))
        if makefile.exists()
        else set()
    )
    for checador in sorted(no_build - reivindicados):
        falhas.append(
            f"tests/invariants/{checador}: roda no build e nenhuma afirmacao o reivindica — "
            "nomeie-o no AGENTS.md onde a regra que ele verifica e escrita"
        )
    return falhas


def main() -> int:
    falhas = verificar(RAIZ)
    print("ainda nao cobertos por este checador:")
    for item in AINDA_NAO_COBERTOS:
        print(f"  - {item}")
    if falhas:
        print("\nafirmacao sem mecanismo, ou mecanismo sem afirmacao:")
        for falha in falhas:
            print(f"  - {falha}")
        return 1
    print("\nafirmacao tem mecanismo, e mecanismo tem afirmacao, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
