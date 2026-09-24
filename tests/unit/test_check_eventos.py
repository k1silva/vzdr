"""O checador de contrato de eventos.

Ele fecha a classe que nem quem escreve nem quem revisa alcança olhando diff:
um diff não mostra ausência. Os testes cobrem os dois sentidos, porque olhar um
só daria a sensação de ter fechado a classe inteira.
"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_eventos import (  # noqa: E402
    VISAO,
    declarados,
    dominios,
    e_evento,
    gerar_visao,
    respeita_a_convencao,
    verificar,
)

VALIDOS = {"tenancy", "dr"}


def montar(tmp_path, *, spec="", codigo="", teste="", visao=None):
    """Um repositório de mentira, com um pacote e um domínio."""
    pacote = tmp_path / "packages" / "core-tenancy" / "src" / "vzdr" / "core" / "tenancy"
    pacote.mkdir(parents=True)
    (pacote / "py.typed").write_text("")
    (pacote / "codigo.py").write_text(codigo or "x = 1\n")
    (tmp_path / "packages" / "core-tenancy" / "pyproject.toml").write_text("[project]\n")

    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "spec.md").write_text(spec)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(teste or "")
    (tmp_path / "docs").mkdir()

    if visao is None:
        decl = declarados(tmp_path, dominios(tmp_path))
        from check_eventos import emitidos

        emit, _ = emitidos(tmp_path, dominios(tmp_path))
        visao = gerar_visao(decl, emit)
    (tmp_path / VISAO).write_text(visao)
    return tmp_path


TABELA = """## Eventos

| Evento | Quando |
| --- | --- |
| `tenancy.papel_concedido` | alguém concedeu |
"""


def test_declarado_emitido_e_testado_passa(tmp_path):
    raiz = montar(
        tmp_path,
        spec=TABELA,
        codigo='EVENTO = "tenancy.papel_concedido"\n',
        teste="from x import EVENTO\n",
    )
    assert verificar(raiz) == []


def test_declarado_e_nao_emitido_reprova(tmp_path):
    """O caso que motivou o checador: contrato sem implementação."""
    raiz = montar(tmp_path, spec=TABELA)
    (falha,) = [f for f in verificar(raiz) if "nunca emitido" in f]
    assert "tenancy.papel_concedido" in falha


def test_emitido_e_nao_declarado_reprova(tmp_path):
    """O espelho, e o pior dos dois: quem consome não sabe que existe."""
    raiz = montar(
        tmp_path,
        codigo='def f():\n    return "tenancy.papel_concedido"\n',
        teste='x = "tenancy.papel_concedido"\n',
    )
    assert any("nao declarado" in f for f in verificar(raiz))


def test_emitido_e_declarado_sem_teste_reprova(tmp_path):
    """'Aparece no código' se satisfaz com código morto."""
    raiz = montar(tmp_path, spec=TABELA, codigo='EVENTO = "tenancy.papel_concedido"\n')
    assert any("nenhum teste o cita" in f for f in verificar(raiz))


def test_a_visao_desatualizada_reprova(tmp_path):
    raiz = montar(
        tmp_path,
        spec=TABELA,
        codigo='EVENTO = "tenancy.papel_concedido"\n',
        teste="from x import EVENTO\n",
        visao="# Eventos\n\nmentira\n",
    )
    assert any(VISAO in f for f in verificar(raiz))


# --------------------------------------------------------------------------
# Declaração é estrutural, não textual.
# --------------------------------------------------------------------------


def test_nome_em_prosa_nao_e_declaracao(tmp_path):
    """Medido antes de decidir: a prosa deste repositório tem 18 nomes que
    casam com o padrão, quase todos lixo — e um perigoso, o
    `dr.concluir_ciclo`, citado num ADR como exemplo de COMO NÃO NOMEAR."""
    prosa = "O evento `tenancy.papel_concedido` é emitido quando alguém concede.\n"
    raiz = montar(tmp_path, spec=prosa)
    assert declarados(raiz, VALIDOS) == {}


def test_tabela_fora_de_secao_de_eventos_nao_conta(tmp_path):
    fora = "## Outra coisa\n\n| Evento | Quando |\n| --- | --- |\n| `tenancy.x_criado` | y |\n"
    raiz = montar(tmp_path, spec=fora)
    assert declarados(raiz, VALIDOS) == {}


# --------------------------------------------------------------------------
# O domínio vem dos pacotes.
# --------------------------------------------------------------------------


def test_o_dominio_sai_dos_pacotes(tmp_path):
    raiz = montar(tmp_path)
    assert dominios(raiz) == {"tenancy"}


def test_guc_da_rls_nao_e_evento():
    """`vzdr.tenant_id` casa com o padrão e não é evento: `vzdr` não é domínio
    de feature nenhuma. Era falso positivo do primeiro inventário."""
    assert e_evento("vzdr.tenant_id", VALIDOS) is False
    assert e_evento("tenancy.papel_concedido", VALIDOS) is True


@pytest.mark.parametrize("nome", ["spec.md", "hashlib.scrypt", "auditoria.tenant_id"])
def test_lixo_da_prosa_nao_casa(nome):
    assert e_evento(nome, VALIDOS) is False


# --------------------------------------------------------------------------
# A convenção de nome. Heurística, com os limites escritos.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nome",
    [
        "tenancy.papel_concedido",
        "tenancy.concessao_negada",
        "tenancy.plataforma_iniciada",
        "dr.ciclo_concluido",
        "dr.janela_aberta",
    ],
)
def test_participio_passa(nome):
    assert respeita_a_convencao(nome) is True


def test_imperativo_reprova():
    """`dr.concluir_ciclo` é o exemplo que o ADR-0005 dá do que não fazer."""
    assert respeita_a_convencao("dr.concluir_ciclo") is False


def test_o_limite_conhecido_da_heuristica():
    """Ela aceita substantivo terminado em -to/-ta. Está no docstring, e o
    conserto de um erro dela é melhorar a heurística ou renomear — nunca
    acrescentar exceção."""
    assert respeita_a_convencao("dr.ponto") is True


def test_o_repositorio_de_verdade_confere():
    """O que o checador promete, afirmado sobre este repositório."""
    assert verificar(RAIZ) == []
