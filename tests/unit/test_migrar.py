"""A decisao do executor de migracao, testada sem banco.

`planejar` recebe o estado em vez de consultar, entao as quatro formas de
divergencia entre disco e banco sao testaveis aqui.
"""

import pytest

from scripts.migrar import (
    MigracaoAlteradaError,
    MigracaoAusenteError,
    MigracaoForaDeOrdemError,
    descobrir,
    planejar,
    sha256_de,
)


def escrever(pasta, nome, conteudo="create table x (id int);"):
    arq = pasta / nome
    arq.write_text(conteudo, encoding="utf-8")
    return arq


def test_descobre_em_ordem_lexicografica(tmp_path):
    escrever(tmp_path, "0003_c.sql")
    escrever(tmp_path, "0001_a.sql")
    escrever(tmp_path, "0002_b.sql")
    assert [m.nome for m in descobrir(tmp_path)] == [
        "0001_a.sql",
        "0002_b.sql",
        "0003_c.sql",
    ]


def test_ordem_nao_e_a_do_filesystem(tmp_path):
    """0010 vem depois de 0009; a ordem e do nome, nao da data de criacao."""
    escrever(tmp_path, "0010_j.sql")
    escrever(tmp_path, "0009_i.sql")
    assert [m.nome for m in descobrir(tmp_path)] == ["0009_i.sql", "0010_j.sql"]


def test_ignora_o_que_nao_e_sql(tmp_path):
    escrever(tmp_path, "0001_a.sql")
    (tmp_path / "README.md").write_text("nao sou migracao")
    (tmp_path / "0002_b.sql.bak").write_text("nem eu")
    assert [m.nome for m in descobrir(tmp_path)] == ["0001_a.sql"]


def test_pasta_ausente_nao_quebra(tmp_path):
    assert descobrir(tmp_path / "nao-existe") == []


def test_sha_muda_com_o_conteudo():
    assert sha256_de("a") != sha256_de("b")
    assert sha256_de("a") == sha256_de("a")


def test_tudo_pendente_num_banco_limpo(tmp_path):
    escrever(tmp_path, "0001_a.sql")
    escrever(tmp_path, "0002_b.sql")
    disponiveis = descobrir(tmp_path)
    assert [m.nome for m in planejar(disponiveis, {})] == ["0001_a.sql", "0002_b.sql"]


def test_nada_pendente_quando_tudo_ja_foi_aplicado(tmp_path):
    escrever(tmp_path, "0001_a.sql")
    disponiveis = descobrir(tmp_path)
    aplicadas = {m.nome: m.sha256 for m in disponiveis}
    assert planejar(disponiveis, aplicadas) == []


def test_so_o_que_falta(tmp_path):
    escrever(tmp_path, "0001_a.sql")
    escrever(tmp_path, "0002_b.sql")
    disponiveis = descobrir(tmp_path)
    aplicadas = {disponiveis[0].nome: disponiveis[0].sha256}
    assert [m.nome for m in planejar(disponiveis, aplicadas)] == ["0002_b.sql"]


def test_arquivo_alterado_depois_de_aplicado_falha(tmp_path):
    escrever(tmp_path, "0001_a.sql", "create table x (id int);")
    aplicadas = {"0001_a.sql": sha256_de("create table x (id int);")}
    escrever(tmp_path, "0001_a.sql", "create table x (id bigint);")
    with pytest.raises(MigracaoAlteradaError) as erro:
        planejar(descobrir(tmp_path), aplicadas)
    assert "0001_a.sql" in str(erro.value)
    assert "no banco" in str(erro.value) and "no disco" in str(erro.value)


def test_migracao_registrada_que_sumiu_do_disco_falha(tmp_path):
    escrever(tmp_path, "0002_b.sql")
    aplicadas = {"0001_a.sql": "qualquer"}
    with pytest.raises(MigracaoAusenteError) as erro:
        planejar(descobrir(tmp_path), aplicadas)
    assert "0001_a.sql" in str(erro.value)


def test_migracao_nova_que_ordena_antes_de_uma_aplicada_falha(tmp_path):
    """Alguem abre 0002 enquanto 0003 ja rodou. Aplicar daria um esquema
    diferente do que a mesma pasta produz num banco limpo."""
    escrever(tmp_path, "0002_b.sql")
    escrever(tmp_path, "0003_c.sql")
    aplicadas = {m.nome: m.sha256 for m in descobrir(tmp_path) if m.nome == "0003_c.sql"}
    with pytest.raises(MigracaoForaDeOrdemError) as erro:
        planejar(descobrir(tmp_path), aplicadas)
    assert "0002_b.sql" in str(erro.value)


def test_migracao_nova_depois_da_ultima_passa(tmp_path):
    escrever(tmp_path, "0001_a.sql")
    escrever(tmp_path, "0002_b.sql")
    aplicadas = {m.nome: m.sha256 for m in descobrir(tmp_path) if m.nome == "0001_a.sql"}
    assert [m.nome for m in planejar(descobrir(tmp_path), aplicadas)] == ["0002_b.sql"]


def test_alteracao_vence_fora_de_ordem(tmp_path):
    """Divergencia de conteudo e reportada antes de ordem: e a mais grave."""
    escrever(tmp_path, "0002_b.sql", "novo")
    escrever(tmp_path, "0003_c.sql", "tambem novo")
    aplicadas = {"0003_c.sql": sha256_de("era outra coisa")}
    with pytest.raises(MigracaoAlteradaError):
        planejar(descobrir(tmp_path), aplicadas)


def test_migracao_vazia_e_valida(tmp_path):
    """Arquivo vazio nao e erro: pode ser um placeholder deliberado."""
    escrever(tmp_path, "0001_a.sql", "")
    assert [m.nome for m in planejar(descobrir(tmp_path), {})] == ["0001_a.sql"]
