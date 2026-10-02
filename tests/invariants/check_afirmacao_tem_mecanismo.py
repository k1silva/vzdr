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
     apontando para ela reprova: o mecanismo tinha que ter sido nomeado;
   - `C-005` — a candidata existe em `## Candidatas` de docs/pendencias.md. E a
     forma de dizer "decidimos que importa, nao decidimos como", e e a mais facil
     de abusar: candidata e barata de escrever. Por isso ela SO vale numa
     afirmacao REBAIXADA — a que uma emenda deixou de chamar de aceita, marcada no
     proprio titulo —, e nunca sustenta decisao viva. E o checador imprime, em toda
     execucao, quantas afirmacoes estao sustentadas so por candidata: pressao
     visivel, e nao portao. Portao empurraria a inventar mecanismo, que e pior do
     que admitir que ele nao existe.
3. **A volta, que e a metade que se esquece: todo checador no build e
   reivindicado.** Por uma referencia num documento coberto, ou pelo nome do
   arquivo, em crase, no AGENTS.md — em QUALQUER lugar dele. O checador nao confere
   se a mencao esta na secao que descreve a regra: nao ha forma estrutural para
   isso, e prometer o que nao se confere e o docstring que afirma o que o codigo
   nao faz. E o AGENTS.md, alem de reivindicar, e AUDITADO: todo arquivo que ele
   nomeia tem que existir. Sem isto acumulam checadores orfaos, e o
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

#: O universo de documentos com afirmacao cruzada. O que NAO e coberto e derivado
#: dele por subtracao, e nunca escrito a mao: a primeira versao tinha uma tupla
#: literal, e uma spec ou um ADR novo nasceria invisivel — o relatorio continuaria
#: parecendo completo, e a limitacao deixaria de ser visivel sem deixar de estar
#: escrita. Quarta vez do padrao "lista a mao contra o catalogo real", e desta vez
#: dentro do checador que existe para pegar isso.
UNIVERSO = ("specs/*/plan.md", "specs/*/spec.md", "docs/adr/*.md")
#: Fora do universo: moldes, que nao afirmam nada.
MOLDES = ("specs/_template/", "docs/adr/template.md")


def ainda_nao_cobertos(raiz: Path) -> list[str]:
    """Todo documento do universo que nao esta coberto — fato, e nao memoria."""
    cobertos = set(COBERTOS_PLANO) | set(COBERTOS_ADR)
    todos = {
        caminho.relative_to(raiz).as_posix() for padrao in UNIVERSO for caminho in raiz.glob(padrao)
    }
    return sorted(d for d in todos - cobertos if not any(d.startswith(m) or d == m for m in MOLDES))


TAREFAS = {"specs/dr-001-dominio-ciclo/plan.md": "specs/dr-001-dominio-ciclo/tasks.md"}
MEDICOES = "docs/adr/0012-resposta-a-perda-de-bitmap.md"
PENDENCIAS = "docs/pendencias.md"

_CRASE = re.compile(r"`([^`]+)`")
_TESTE = re.compile(r"(?P<arquivo>(?:tests|scripts|packages)/[\w/.-]+\.py)::(?P<funcao>test_\w+)")
_ARQUIVO = re.compile(r"(?:tests|scripts|packages)/[\w/.-]+\.py")
_MEDICAO = re.compile(r"M\d+")
_TAREFA = re.compile(r"T\d+")
_CANDIDATA = re.compile(r"C-\d{3}")
#: O titulo da afirmacao diz que ela foi rebaixada. E onde a emenda declara que
#: deixou de chamar aquilo de aceito — e o unico lugar em que candidata vale.
_REBAIXADA = re.compile(r"rebaixad[ao]", re.IGNORECASE)
#: `dr-001/T6` — tarefa com a spec dita. Obrigatoria fora de um plano: num ADR, `T6`
#: solto nao diz de qual spec e a tarefa.
_TAREFA_QUALIFICADA = re.compile(r"(?P<spec>[a-z]+-\d+)/(?P<tarefa>T\d+)")
_CHECADOR_NO_MAKEFILE = re.compile(r"tests/invariants/(check_\w+\.py)")
#: Checador nomeado so pelo arquivo, como o AGENTS.md costuma fazer.
_CHECADOR_SOLTO = re.compile(r"check_\w+\.py")


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
            or _CANDIDATA.fullmatch(item)
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
    #: O PARAGRAFO inteiro do `**Mecanismo:**`, e nao so a primeira linha. A
    #: primeira versao lia a linha do rotulo: referencia quebrada para a linha
    #: seguinte nao era vista nos dois sentidos — a afirmacao reprovava como "sem
    #: mecanismo" se todas estivessem na continuacao, e uma referencia a teste que
    #: nao existe, na continuacao, passava sem ser conferida.
    no_mecanismo = False
    for _, linha in linhas_fora_de_blocos(texto):
        if linha.startswith("## "):
            secao = linha.strip()
            atual = None
            no_mecanismo = False
            continue
        if secao not in ("## Decisão", "## Decisao"):
            continue
        casou = re.match(r"### (\d+)\. (.*)", linha)
        if casou:
            atual = f"propriedade {casou.group(1)}: {casou.group(2).strip()}"
            refs[atual] = []
            ordem.append(atual)
            no_mecanismo = False
            continue
        if not linha.strip():
            no_mecanismo = False
            continue
        if atual and linha.startswith("**Mecanismo:**"):
            no_mecanismo = True
        if atual and no_mecanismo:
            refs[atual].extend(referencias(linha))
    return [(r, refs[r]) for r in ordem]


def _medicoes(raiz: Path) -> set[str]:
    caminho = raiz / MEDICOES
    if not caminho.exists():
        return set()
    return set(re.findall(r"^\| (M\d+) \|", caminho.read_text(encoding="utf-8"), re.MULTILINE))


def _candidatas(raiz: Path) -> set[str]:
    """Os ids da secao `## Candidatas` — so dela: aberta tem prazo e outro papel,
    fechada nao sustenta nada."""
    caminho = raiz / PENDENCIAS
    if not caminho.exists():
        return set()
    dentro = False
    ids = set()
    for _, linha in linhas_fora_de_blocos(caminho.read_text(encoding="utf-8")):
        if linha.startswith("## "):
            dentro = linha.strip() == "## Candidatas"
            continue
        casou = re.match(r"- \*\*(C-\d{3})\b", linha)
        if dentro and casou:
            ids.add(casou.group(1))
    return ids


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
    if _CANDIDATA.fullmatch(ref):
        if ref not in _candidatas(raiz):
            return f"`{ref}`: nao ha candidata com esse id em {PENDENCIAS}"
        return None
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
                if _CANDIDATA.fullmatch(ref) and not _REBAIXADA.search(rotulo):
                    falhas.append(
                        f"{documento}: '{rotulo}': `{ref}`: candidata so sustenta afirmacao "
                        f"rebaixada — marque no titulo que a emenda a rebaixou, ou nomeie o "
                        f"mecanismo"
                    )
                if _ARQUIVO.fullmatch(ref):
                    reivindicados.add(Path(ref).name)
                elif _TESTE.fullmatch(ref):
                    reivindicados.add(Path(ref.split("::")[0]).name)

    agents = raiz / "AGENTS.md"
    if agents.exists():
        # O AGENTS.md reivindica, e tambem AFIRMA. Colher reivindicacao sem auditar
        # afirmacao deixava o espelho da regra 3 descoberto: apague um checador e a
        # linha dele no Makefile, deixe a do AGENTS.md de pe — a regra 3 nao
        # dispara, porque o checador saiu do build, e a regra 2 nao dispara, porque
        # o AGENTS.md nao era auditado. Tudo verde, e o documento mentindo.
        for _, linha in linhas_fora_de_blocos(agents.read_text(encoding="utf-8")):
            for item in _CRASE.findall(linha):
                item = item.strip()
                if _TESTE.fullmatch(item) or _ARQUIVO.fullmatch(item):
                    problema = _problema_da_referencia(raiz, item, {}, medicoes)
                elif _CHECADOR_SOLTO.fullmatch(item):
                    existe = (raiz / "tests" / "invariants" / item).exists()
                    problema = None if existe else f"`{item}`: o checador nao existe"
                else:
                    continue
                if problema:
                    falhas.append(f"AGENTS.md: {problema}")
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
            "nomeie-o, em crase, no AGENTS.md ou num documento coberto"
        )
    return falhas


def sustentadas_por_candidata(raiz: Path) -> list[str]:
    """Afirmacoes cujo unico sustento e candidata. Impresso, e nao reprovado."""
    cobertos = [(d, afirmacoes_do_plano) for d in COBERTOS_PLANO] + [
        (d, afirmacoes_do_adr) for d in COBERTOS_ADR
    ]
    saida = []
    for documento, extrair in cobertos:
        caminho = raiz / documento
        if not caminho.exists():
            continue
        for rotulo, refs in extrair(caminho.read_text(encoding="utf-8")):
            if refs and all(_CANDIDATA.fullmatch(r) for r in refs):
                saida.append(f"{documento}: '{rotulo}'")
    return saida


def main() -> int:
    falhas = verificar(RAIZ)
    faltam = ainda_nao_cobertos(RAIZ)
    print(f"ainda nao cobertos por este checador ({len(faltam)}):")
    for item in faltam:
        print(f"  - {item}")
    so_candidata = sustentadas_por_candidata(RAIZ)
    print(f"\nsustentadas so por candidata ({len(so_candidata)}):")
    for item in so_candidata:
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
