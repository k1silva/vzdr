#!/usr/bin/env python3
"""Confere que evento declarado e evento emitido sao o mesmo conjunto.

Nos dois sentidos, e o segundo nao e simetrico do primeiro:

- **declarado e nao emitido** — contrato escrito sem implementacao. Foi o
  `tenancy.tenant_trocado`, exigido pela T11 e ausente do codigo, que passou na
  revisao porque um diff nao mostra ausencia;
- **emitido e nao declarado** — implementacao sem contrato. Foi o
  `autenticar_plataforma`, que existia no codigo e nao na `tasks.md`. Para um
  sistema com contrato de eventos este e o pior dos dois, porque quem consome
  nao sabe que existe.

Olhar um lado so fecharia metade da classe e daria a sensacao de ter fechado
inteira — que e o padrao que este checador existe para matar. O inventario
provou: quando ele foi escrito havia 7 emitidos e 0 declarados.

## O que conta como DECLARACAO

Posicao, nao texto. So vale nome na primeira coluna de uma tabela sob um
cabecalho `Eventos`:

    ## Eventos

    | Evento | Quando |
    | --- | --- |
    | `tenancy.papel_concedido` | admin concede papel a outro |

Nome em crase no meio de um paragrafo NAO e declaracao. Medido antes de decidir:
a prosa deste repositorio tem 18 nomes que casam com o padrao, quase todos lixo
(`spec.md`, `pyproject.toml`, `hashlib.scrypt`) — e um perigoso, o
`dr.concluir_ciclo`, que o ADR-0005 cita como exemplo de COMO NAO NOMEAR. Por
texto, um exemplo do que nao fazer viraria contrato.

## O que conta como EMITIDO

Emitido **e testado**. "Aparece no codigo" se satisfaz com codigo morto, e esta
fatia ja teve uma guarda que ninguem chamava e um ramo que nenhum teste
alcancava: sem o teste no criterio, o checador aceitaria exatamente aquilo.

## O dominio vem dos pacotes

`dominio.acao` (ADR-0005), e o dominio e o modulo dono — derivado de
`packages/*/src/**/py.typed`, nao de lista a mao. Mesmo principio do `MYPY_SRC`:
pacote novo entra sozinho. E resolve de graca o falso positivo do
`vzdr.tenant_id`, que e o nome do GUC da RLS: `vzdr` nao e dominio de feature
nenhuma.

## A convencao de nome, e o que ela nao alcanca

O ADR-0005 exige particípio, nao imperativo: evento descreve o que aconteceu.
Em portugues isso vira heuristica de sufixo no ultimo termo — `-ado`, `-ada`,
`-ido`, `-ida`, e os irregulares em `-to`/`-ta` (`aberta`, `escrito`).

Ela erra nos dois sentidos, e vale saber onde: aceita substantivo terminado em
`-to`/`-ta` (`ponto`, `conta`) e recusaria um particípio de forma inesperada. Se
um nome legitimo for recusado, o conserto e melhorar a heuristica ou renomear o
evento — **nao acrescentar excecao**. Lista de excecao de evento nao tem data
natural para expirar, e viraria o carimbo que o `check_pendencias` recusa.

## A visao gerada

`docs/eventos.md` e gerado a partir das specs e **commitado**. O checador
verifica que o arquivo no repositorio e igual ao que o gerador produz; se
diferir, reprova.

Gerado e nao verificado seria a lista desatualizada que a fonte-na-spec quis
evitar, com aparencia de autoridade por parecer gerada. Commitado, e nao gerado
sob demanda, porque quem consome webhook precisa ler no GitHub sem rodar nada.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

DOCS = ("specs", "docs")
FONTE = "packages"
TESTES = "tests"
VISAO = "docs/eventos.md"

CABECALHO_DE_EVENTOS = re.compile(r"^#{1,6}\s+Eventos\s*$", re.MULTILINE)
LINHA_DE_TABELA = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*$")
FORMA = re.compile(r"^([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]+)$")

#: Sufixos de particípio em portugues, incluindo os irregulares. Heuristica —
#: ver "A convencao de nome" no topo.
PARTICIPIO = ("ado", "ada", "ido", "ida", "to", "ta")


def dominios(raiz: Path) -> set:
    """Os modulos folha do repositorio. Derivado, nao listado."""
    return {
        marcador.parent.name
        for pyproj in sorted(raiz.glob("packages/*/pyproject.toml"))
        for marcador in (pyproj.parent / "src").rglob("py.typed")
    }


def e_evento(nome: str, validos: set) -> bool:
    m = FORMA.match(nome)
    return bool(m) and m.group(1) in validos


def respeita_a_convencao(nome: str) -> bool:
    """Particípio, nao imperativo (ADR-0005). Heuristica de sufixo."""
    acao = FORMA.match(nome).group(2)  # type: ignore[union-attr]
    return acao.rsplit("_", 1)[-1].endswith(PARTICIPIO)


def declarados(raiz: Path, validos: set) -> dict:
    """{evento: (arquivo, descricao)} das tabelas sob cabecalho `Eventos`."""
    achados: dict = {}
    for pasta in DOCS:
        base = raiz / pasta
        if not base.exists():
            continue
        for doc in sorted(base.rglob("*.md")):
            if str(doc.relative_to(raiz)) == VISAO:
                continue
            texto = doc.read_text(encoding="utf-8")
            for marca in CABECALHO_DE_EVENTOS.finditer(texto):
                resto = texto[marca.end() :]
                fim = re.search(r"^#{1,6}\s", resto, re.MULTILINE)
                for linha in (resto[: fim.start()] if fim else resto).splitlines():
                    m = LINHA_DE_TABELA.match(linha)
                    if m and e_evento(m.group(1), validos):
                        achados[m.group(1)] = (str(doc.relative_to(raiz)), m.group(2))
    return achados


def _literais_e_constantes(arquivo: Path, validos: set) -> tuple[set, dict]:
    try:
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    except SyntaxError:  # pragma: no cover
        return set(), {}
    literais = {
        no.value
        for no in ast.walk(arvore)
        if isinstance(no, ast.Constant)
        and isinstance(no.value, str)
        and e_evento(no.value, validos)
    }
    constantes = {
        alvo.id: no.value.value
        for no in arvore.body
        if isinstance(no, ast.Assign)
        and isinstance(no.value, ast.Constant)
        and isinstance(no.value.value, str)
        and e_evento(no.value.value, validos)
        for alvo in no.targets
        if isinstance(alvo, ast.Name)
    }
    return literais, constantes


def emitidos(raiz: Path, validos: set) -> tuple[dict, dict]:
    achados: dict = {}
    constantes: dict = {}
    base = raiz / FONTE
    if not base.exists():
        return achados, constantes
    for arquivo in sorted(base.rglob("*.py")):
        literais, consts = _literais_e_constantes(arquivo, validos)
        for evento in literais:
            achados.setdefault(evento, set()).add(str(arquivo.relative_to(raiz)))
        constantes.update(consts)
    return achados, constantes


def testados(raiz: Path, validos: set, constantes: dict) -> set:
    """Citados nos testes, por literal ou pelo nome da constante."""
    base = raiz / TESTES
    if not base.exists():
        return set()
    vistos: set = set()
    for arquivo in sorted(base.rglob("*.py")):
        texto = arquivo.read_text(encoding="utf-8")
        literais, _ = _literais_e_constantes(arquivo, validos)
        vistos |= literais
        for nome, evento in constantes.items():
            if re.search(rf"\b{re.escape(nome)}\b", texto):
                vistos.add(evento)
    return vistos


def gerar_visao(decl: dict, emit: dict) -> str:
    linhas = [
        "# Eventos",
        "",
        "> **Gerado** por `tests/invariants/check_eventos.py`. Não edite à mão: o",
        "> checador reprova se este arquivo divergir das specs.",
        "",
        "A fonte de cada evento é a seção `Eventos` da spec da feature que o emite.",
        "Esta página só reúne as fontes para quem consome webhook conseguir ler tudo",
        "de uma vez.",
        "",
        "| Evento | Quando | Declarado em | Emitido em |",
        "| --- | --- | --- | --- |",
    ]
    for evento in sorted(decl):
        arquivo, quando = decl[evento]
        onde = ", ".join(f"`{c}`" for c in sorted(emit.get(evento, ())))
        linhas.append(f"| `{evento}` | {quando} | `{arquivo}` | {onde} |")
    linhas.append("")
    return "\n".join(linhas)


def verificar(raiz: Path) -> list:
    validos = dominios(raiz)
    decl = declarados(raiz, validos)
    emit, constantes = emitidos(raiz, validos)
    test = testados(raiz, validos, constantes)
    falhas = []

    for evento in sorted(set(decl) - set(emit)):
        falhas.append(
            f"{evento}: declarado em {decl[evento][0]} e nunca emitido.\n"
            f"      Contrato sem implementacao. Implemente, ou tire da tabela."
        )
    for evento in sorted(set(emit) - set(decl)):
        falhas.append(
            f"{evento}: emitido em {', '.join(sorted(emit[evento]))} e nao declarado.\n"
            f"      Quem consome nao sabe que existe. Declare na secao `Eventos` da spec."
        )
    for evento in sorted(set(emit) & set(decl) - test):
        falhas.append(
            f"{evento}: emitido e declarado, mas nenhum teste o cita.\n"
            f"      'Aparece no codigo' se satisfaz com codigo morto."
        )
    for evento in sorted(set(decl) | set(emit)):
        if not respeita_a_convencao(evento):
            falhas.append(
                f"{evento}: a acao nao parece particípio (ADR-0005).\n"
                f"      Evento descreve o que aconteceu, nao o que se pede.\n"
                f"      Se o nome esta certo e a heuristica errou, melhore a\n"
                f"      heuristica ou renomeie — nao acrescente excecao."
            )

    esperado = gerar_visao(decl, emit)
    caminho = raiz / VISAO
    atual = caminho.read_text(encoding="utf-8") if caminho.exists() else ""
    if atual != esperado:
        falhas.append(
            f"{VISAO} esta desatualizado.\n"
            f"      Rode: make eventos\n"
            f"      Gerado e nao verificado vira lista velha com cara de autoridade."
        )
    return falhas


def main(argv: list) -> int:
    validos = dominios(RAIZ)
    if "--gerar" in argv:
        decl = declarados(RAIZ, validos)
        emit, _ = emitidos(RAIZ, validos)
        (RAIZ / VISAO).write_text(gerar_visao(decl, emit), encoding="utf-8")
        print(f"{VISAO} gerado ({len(decl)} evento(s))")
        return 0

    falhas = verificar(RAIZ)
    if falhas:
        print("Contrato de eventos e codigo divergem:")
        for f in falhas:
            print("  " + f)
        return 1
    print(f"eventos: contrato e codigo conferem ({len(declarados(RAIZ, validos))})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
