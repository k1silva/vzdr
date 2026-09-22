"""O executor de migracao contra um Postgres de verdade.

A logica de decisao esta em tests/unit/test_migrar.py. Aqui esta o que so o
banco prova: transacao por arquivo, registro junto do DDL, e idempotencia.
"""

import pytest

from scripts.migrar import ConexaoSemAutocommitError, migrar

pytestmark = pytest.mark.db


def escrever(pasta, nome, sql):
    (pasta / nome).write_text(sql, encoding="utf-8")


def tabelas(conexao, esquema):
    with conexao.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables where table_schema = %s",
            (esquema,),
        )
        return {linha[0] for linha in cur.fetchall()}


def registradas(conexao):
    with conexao.cursor() as cur:
        cur.execute("select nome from schema_migrations order by nome")
        return [linha[0] for linha in cur.fetchall()]


def test_aplica_em_ordem(conexao, esquema_limpo, tmp_path):
    escrever(tmp_path, "0002_b.sql", "create table b (id int);")
    escrever(tmp_path, "0001_a.sql", "create table a (id int);")

    assert migrar(conexao, tmp_path) == ["0001_a.sql", "0002_b.sql"]
    assert {"a", "b"} <= tabelas(conexao, esquema_limpo)
    assert registradas(conexao) == ["0001_a.sql", "0002_b.sql"]


@pytest.mark.usefixtures("esquema_limpo")
def test_rodar_duas_vezes_e_inocuo(conexao, tmp_path):
    escrever(tmp_path, "0001_a.sql", "create table a (id int);")

    assert migrar(conexao, tmp_path) == ["0001_a.sql"]
    assert migrar(conexao, tmp_path) == []
    assert registradas(conexao) == ["0001_a.sql"]


def test_falha_no_meio_do_arquivo_nao_deixa_esquema_parcial(conexao, esquema_limpo, tmp_path):
    """P4, mesma disciplina do ciclo: interromper nao corrompe.

    O arquivo cria uma tabela e depois falha. Nem a tabela nem o registro podem
    sobreviver — senao a proxima rodada pula uma migracao que nao aconteceu.
    """
    import psycopg

    escrever(
        tmp_path,
        "0001_a.sql",
        "create table a (id int); create table a (id int);",  # segunda falha
    )

    with pytest.raises(psycopg.Error):
        migrar(conexao, tmp_path)

    assert "a" not in tabelas(conexao, esquema_limpo)
    assert registradas(conexao) == []


def test_falha_num_arquivo_preserva_os_anteriores(conexao, esquema_limpo, tmp_path):
    """O que ja commitou fica; so o arquivo que falhou e desfeito."""
    import psycopg

    escrever(tmp_path, "0001_a.sql", "create table a (id int);")
    escrever(tmp_path, "0002_b.sql", "create table b (id int); isto nao e sql;")

    with pytest.raises(psycopg.Error):
        migrar(conexao, tmp_path)

    assert "a" in tabelas(conexao, esquema_limpo)
    assert "b" not in tabelas(conexao, esquema_limpo)
    assert registradas(conexao) == ["0001_a.sql"]


def test_registro_e_ddl_na_mesma_transacao(conexao, esquema_limpo, tmp_path):
    """Nao pode existir estado onde o DDL passou e o registro nao."""
    escrever(tmp_path, "0001_a.sql", "create table a (id int);")
    migrar(conexao, tmp_path)

    with conexao.cursor() as cur:
        cur.execute("select sha256 from schema_migrations where nome = %s", ("0001_a.sql",))
        assert cur.fetchone() is not None
    assert "a" in tabelas(conexao, esquema_limpo)


@pytest.mark.usefixtures("esquema_limpo")
def test_conexao_sem_autocommit_e_recusada(conexao, tmp_path):
    """Sem autocommit, transaction() vira savepoint e o contrato cai em silencio."""
    escrever(tmp_path, "0001_a.sql", "create table a (id int);")
    conexao.autocommit = False
    with pytest.raises(ConexaoSemAutocommitError):
        migrar(conexao, tmp_path)


def test_tabela_de_controle_nasce_sozinha(conexao, esquema_limpo, tmp_path):
    """Banco limpo: o executor cria schema_migrations antes de precisar dela."""
    assert migrar(conexao, tmp_path) == []
    assert "schema_migrations" in tabelas(conexao, esquema_limpo)
