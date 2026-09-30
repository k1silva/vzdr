"""Arnes de mutacao: confirma que um teste REPROVA quando o controle e desligado.

O AGENTS.md manda mutar todo controle de seguranca e confirmar que o teste
reprova. Este script e o que torna isso confiavel, e ele existe porque a versao
feita a mao falhou de um jeito que produz verde falso.

GARANTIAS, por construcao e nao por lembranca:

- **Processo novo por rodada.** O pytest roda em subprocesso, entao nada fica em
  `sys.modules` de uma rodada para a outra.
- **Sem bytecode, e cache apagado antes e depois de cada rodada** — prevencao, e
  nao garantia testada: o Python valida o `.pyc` pela data em segundos e pelo
  tamanho do fonte, e mutacao do mesmo tamanho desfeita no mesmo segundo deixava o
  bytecode da versao mutada valendo sobre o fonte restaurado. Depende de tempo, e
  nenhum teste deterministico o reproduz.
- **Verde depois de restaurar, antes de seguir.** Esta e a que pega a CLASSE, e nao
  so as duas causas conhecidas. Se a restauracao nao restaurou — bytecode velho,
  modulo em memoria, escrita malfeita, arquivo trocado —, a rodada seguinte seria
  sobre outra coisa. Exigir verde apos cada restauro pega qualquer uma delas, sem
  precisar saber qual foi.
- **Linha de base verde.** Mutar sobre suite ja vermelha nao prova nada: toda
  mutacao "reprovaria".
- **Ancora errada e erro, nunca pulo.** A versao a mao imprimia "ANCORA ERRADA" e
  seguia — uma mutacao que nao roda, contada como se tivesse rodado.

Uso: `make mutacao M=caminho/para/mutacoes.json`, com
`{"arquivo": ..., "testes": [...], "mutacoes": {"nome": ["velho", "novo"]}}`.
"""

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = ["AncoraError", "LinhaDeBaseError", "Rodada", "RestauroFalhouError", "rodar"]


class AncoraError(Exception):
    """O trecho a mutar nao aparece exatamente uma vez."""


class LinhaDeBaseError(Exception):
    """Os testes ja reprovam antes de qualquer mutacao."""


class RestauroFalhouError(Exception):
    """Depois de desfazer a mutacao, os testes nao voltaram ao verde."""


@dataclass(frozen=True)
class Rodada:
    nome: str
    reprovou: bool


Escritor = Callable[[Path, str], None]


def _escrever(caminho: Path, texto: str) -> None:
    caminho.write_text(texto, encoding="utf-8")


def _limpar_cache(raiz: Path) -> None:
    for pasta in raiz.rglob("__pycache__"):
        shutil.rmtree(pasta, ignore_errors=True)


def _testes_passam(raiz: Path, testes: list[str]) -> bool:
    """Um processo novo, sem bytecode, sem cache do pytest.

    `-B` e a limpeza do cache sao PREVENCAO, e nenhum teste as distingue: o
    defeito que elas previnem depende de tempo — mutacao do mesmo tamanho desfeita
    no mesmo segundo —, e nenhum teste deterministico o reproduz. Mutadas com este
    proprio arnes, as duas sobrevivem, e isso esta registrado aqui em vez de
    escondido atras de um teste fabricado. Ficam porque sao baratas; uma terceira
    camada, PYTHONDONTWRITEBYTECODE, saiu por nao acrescentar nem isso.

    A GARANTIA que se deixa testar, e que reprova quando retirada, e o verde
    depois de restaurar: ela pega a consequencia, qualquer que seja a causa.
    """
    _limpar_cache(raiz)
    resultado = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *testes,
        ],
        cwd=raiz,
        capture_output=True,
        text=True,
    )
    _limpar_cache(raiz)
    return resultado.returncode == 0


def rodar(
    raiz: Path,
    arquivo: str,
    testes: list[str],
    mutacoes: dict[str, tuple[str, str]],
    escrever: Escritor = _escrever,
) -> list[Rodada]:
    """Aplica cada mutacao, roda, desfaz, e exige verde antes da seguinte.

    Levanta em vez de reportar quando o proprio instrumento nao e confiavel —
    linha de base vermelha, ancora errada, restauro que nao restaurou. Esses nao
    sao resultados de mutacao; sao motivos para nao acreditar em nenhum.
    """
    caminho = raiz / arquivo
    original = caminho.read_text(encoding="utf-8")
    for nome, (velho, _) in mutacoes.items():
        if original.count(velho) != 1:
            raise AncoraError(f"{nome!r}: o trecho aparece {original.count(velho)} vezes, e nao 1")
    if not _testes_passam(raiz, testes):
        raise LinhaDeBaseError("os testes ja reprovam sem mutacao nenhuma")

    rodadas = []
    for nome, (velho, novo) in mutacoes.items():
        try:
            escrever(caminho, original.replace(velho, novo))
            rodadas.append(Rodada(nome=nome, reprovou=not _testes_passam(raiz, testes)))
        finally:
            escrever(caminho, original)
        if not _testes_passam(raiz, testes):
            raise RestauroFalhouError(
                f"depois de desfazer {nome!r}, os testes nao voltaram ao verde — "
                "a rodada seguinte seria sobre outra coisa"
            )
    if caminho.read_text(encoding="utf-8") != original:
        raise RestauroFalhouError(f"{arquivo} nao voltou ao conteudo original")
    return rodadas


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python -m scripts.mutacao <mutacoes.json>")
        return 2
    especificacao = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    mutacoes = {nome: (par[0], par[1]) for nome, par in especificacao["mutacoes"].items()}
    rodadas = rodar(Path.cwd(), especificacao["arquivo"], especificacao["testes"], mutacoes)
    sobreviventes = [r for r in rodadas if not r.reprovou]
    for rodada in rodadas:
        print(f"{'REPROVA ok ' if rodada.reprovou else 'SOBREVIVEU'}  {rodada.nome}")
    return 1 if sobreviventes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
