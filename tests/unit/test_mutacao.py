"""O arnes de mutacao, sobre um projeto minusculo num diretorio temporario.

O que importa aqui e o instrumento, porque ele valida os controles de seguranca:
uma rodada que roda sobre a coisa errada produz verde falso, e verde falso numa
mutacao e "o teste protege" quando nao protege.
"""

from pathlib import Path

import pytest

from scripts.mutacao import AncoraError, LinhaDeBaseError, RestauroFalhouError, rodar

MODULO = "def dobro(x):\n    return x * 2\n"
TESTE = "from modulo import dobro\n\n\ndef test_dobro():\n    assert dobro(3) == 6\n"


def projeto(tmp_path: Path, teste: str = TESTE) -> Path:
    (tmp_path / "modulo.py").write_text(MODULO, encoding="utf-8")
    (tmp_path / "test_modulo.py").write_text(teste, encoding="utf-8")
    return tmp_path


def test_mutacao_que_quebra_reprova(tmp_path):
    (r,) = rodar(projeto(tmp_path), "modulo.py", ["test_modulo.py"], {"soma": ("x * 2", "x + 2")})
    assert r.reprovou


def test_mutacao_que_nao_muda_nada_sobrevive_e_e_reportada(tmp_path):
    """Mutacao sobrevivente e resultado — o teste nao protege aquilo —, e nao erro."""
    (r,) = rodar(projeto(tmp_path), "modulo.py", ["test_modulo.py"], {"neutra": ("x * 2", "2 * x")})
    assert not r.reprovou


def test_mutacao_do_mesmo_tamanho_seguida_de_outra_mede_cada_uma(tmp_path):
    """O caso que mordeu: `* 2` virando `* 3` (mesmo tamanho), e depois uma mutacao
    neutra. Com bytecode velho, a rodada da neutra executaria a anterior e
    "reprovaria" — verde falso ao contrario. Aqui cada rodada mede a si mesma."""
    rodadas = rodar(
        projeto(tmp_path),
        "modulo.py",
        ["test_modulo.py"],
        {"mesmo tamanho": ("x * 2", "x * 3"), "neutra": ("x * 2", "2 * x")},
    )
    assert [r.reprovou for r in rodadas] == [True, False]


def test_ancora_errada_e_erro_e_nao_pulo(tmp_path):
    """A versao a mao imprimia "ANCORA ERRADA" e seguia — mutacao que nao rodou,
    contada como se tivesse rodado."""
    with pytest.raises(AncoraError, match="0 vezes"):
        rodar(projeto(tmp_path), "modulo.py", ["test_modulo.py"], {"x": ("nao existe", "y")})


def test_ancora_repetida_e_erro(tmp_path):
    raiz = projeto(tmp_path)
    (raiz / "modulo.py").write_text(MODULO + MODULO.replace("dobro", "outro"), encoding="utf-8")
    with pytest.raises(AncoraError, match="2 vezes"):
        rodar(raiz, "modulo.py", ["test_modulo.py"], {"x": ("x * 2", "x + 2")})


def test_linha_de_base_vermelha_aborta(tmp_path):
    """Sobre suite ja vermelha, toda mutacao "reprovaria"."""
    raiz = projeto(tmp_path, teste=TESTE.replace("== 6", "== 7"))
    with pytest.raises(LinhaDeBaseError):
        rodar(raiz, "modulo.py", ["test_modulo.py"], {"x": ("x * 2", "x + 2")})


def test_restauro_que_nao_restaura_e_pego(tmp_path):
    """O que pega a CLASSE, qualquer que seja a causa: depois de desfazer, os testes
    tem que voltar ao verde. Aqui a escrita da restauracao e sabotada."""
    raiz = projeto(tmp_path)
    original = (raiz / "modulo.py").read_text(encoding="utf-8")

    def escrita_que_nao_restaura(caminho: Path, texto: str) -> None:
        caminho.write_text(
            texto if texto != original else texto.replace("* 2", "* 9"), encoding="utf-8"
        )

    with pytest.raises(RestauroFalhouError, match="nao voltaram ao verde"):
        rodar(
            raiz,
            "modulo.py",
            ["test_modulo.py"],
            {"x": ("x * 2", "x + 2")},
            escrever=escrita_que_nao_restaura,
        )


def test_o_arquivo_volta_ao_original_byte_a_byte(tmp_path):
    raiz = projeto(tmp_path)
    rodar(raiz, "modulo.py", ["test_modulo.py"], {"a": ("x * 2", "x + 2"), "b": ("x * 2", "x - 2")})
    assert (raiz / "modulo.py").read_text(encoding="utf-8") == MODULO


def test_nao_deixa_bytecode(tmp_path):
    raiz = projeto(tmp_path)
    rodar(raiz, "modulo.py", ["test_modulo.py"], {"a": ("x * 2", "x + 2")})
    assert not list(raiz.rglob("__pycache__"))
