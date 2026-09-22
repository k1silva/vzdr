"""O checador de P9: o que passa, o que falha, e a amarra com a spec.

A regra que a spec escreve — "acrescentar exceção é alterar a spec, não editar o
checador" — só vale se algo verificar. É o ultimo teste daqui.
"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests" / "invariants"))

from check_tenant_id import ISENTAS, SPEC, verificar  # noqa: E402


def montar(tmp_path: Path, arquivos: dict) -> Path:
    pasta = tmp_path / "deploy" / "migrations"
    pasta.mkdir(parents=True)
    for nome, sql in arquivos.items():
        (pasta / nome).write_text(sql, encoding="utf-8")
    return tmp_path


# Cria todas as isentas que alguma migracao deve criar, para nao poluir os
# testes com falhas de excecao morta.
ISENTAS_VIVAS = "\n".join(
    f"create table {nome} (id uuid primary key);"
    for nome, isencao in ISENTAS.items()
    if isencao.criada_por_migracao
)


def test_tabela_com_tenant_id_passa(tmp_path):
    raiz = montar(
        tmp_path,
        {
            "0001.sql": ISENTAS_VIVAS + "\ncreate table vm (id uuid, tenant_id uuid);",
        },
    )
    assert verificar(raiz) == []


def test_tabela_sem_tenant_id_falha(tmp_path):
    raiz = montar(
        tmp_path,
        {
            "0001.sql": ISENTAS_VIVAS + "\ncreate table vm (id uuid, nome text);",
        },
    )
    falhas = verificar(raiz)
    assert len(falhas) == 1
    assert "'vm'" in falhas[0]


def test_mensagem_manda_alterar_a_spec_e_nao_o_checador(tmp_path):
    raiz = montar(tmp_path, {"0001.sql": ISENTAS_VIVAS + "\ncreate table vm (id uuid);"})
    (falha,) = verificar(raiz)
    assert SPEC in falha
    assert "nao aqui" in falha


def test_tabela_isenta_passa_sem_tenant_id(tmp_path):
    raiz = montar(tmp_path, {"0001.sql": ISENTAS_VIVAS})
    assert verificar(raiz) == []


def test_excecao_morta_falha_e_diz_o_porque(tmp_path):
    """Isenta que nenhuma migracao cria: some, ou alguem a herda sem saber."""
    vivas_menos_uma = "\n".join(
        f"create table {nome} (id uuid primary key);"
        for nome, isencao in ISENTAS.items()
        if isencao.criada_por_migracao and nome != "papel_plataforma"
    )
    raiz = montar(tmp_path, {"0001.sql": vivas_menos_uma})
    (falha,) = verificar(raiz)
    assert "excecao morta" in falha
    assert "papel_plataforma" in falha
    assert ISENTAS["papel_plataforma"].porque in falha


def test_schema_migrations_nao_conta_como_excecao_morta(tmp_path):
    """Quem a cria e o executor, nao um arquivo de migracao."""
    raiz = montar(tmp_path, {"0001.sql": ISENTAS_VIVAS})
    assert not any("schema_migrations" in f for f in verificar(raiz))


def test_sem_migracao_nenhuma_nao_falha(tmp_path):
    """Antes da T6 a pasta esta vazia; toda excecao pareceria morta."""
    raiz = montar(tmp_path, {})
    assert verificar(raiz) == []


def test_pasta_ausente_nao_quebra(tmp_path):
    assert verificar(tmp_path) == []


def test_reconhece_if_not_exists_e_nome_qualificado(tmp_path):
    raiz = montar(
        tmp_path,
        {
            "0001.sql": ISENTAS_VIVAS + '\ncreate table if not exists "public"."vm" (id uuid);',
        },
    )
    (falha,) = verificar(raiz)
    assert "'vm'" in falha


def test_varias_migracoes_sao_todas_checadas(tmp_path):
    raiz = montar(
        tmp_path,
        {
            "0001.sql": ISENTAS_VIVAS,
            "0002.sql": "create table vm (id uuid);",
            "0003.sql": "create table volume (id uuid);",
        },
    )
    falhas = verificar(raiz)
    assert len(falhas) == 2


def isentas_da_spec() -> set:
    """Os nomes da tabela de exceções da spec — a fonte da verdade."""
    texto = (RAIZ / SPEC).read_text(encoding="utf-8")
    secao = texto.split("### O que fica fora do eixo de tenant")[1].split("\n## ")[0]
    return {linha.split("`")[1] for linha in secao.splitlines() if linha.startswith("| `")}


def test_checador_e_spec_nao_divergem():
    """A regra da spec: acrescentar exceção é alterar a spec, não editar o checador.

    Sem este teste, a regra é um comentário.
    """
    assert set(ISENTAS) == isentas_da_spec()


@pytest.mark.parametrize("tabela", sorted(ISENTAS))
def test_toda_isenta_tem_justificativa(tabela):
    assert ISENTAS[tabela].porque.strip()
