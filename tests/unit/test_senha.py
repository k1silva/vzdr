"""Hash de senha.

Dois testes aqui existem por causa de armadilhas concretas, não por completude:
o do `maxmem`, porque teste com parâmetros pequenos passa e produção com os
reais quebra; e o do algoritmo desconhecido, porque cair na política vigente
transformaria hash ilegível em "senha inválida".
"""

import base64
import hashlib

import pytest

from vzdr.core.tenancy.senha import (
    ALGORITMO,
    POLITICA,
    AlgoritmoDesconhecidoError,
    ParametrosIlegiveisError,
    Politica,
    hashear,
    precisa_de_rehash,
    verificar,
)

# Parâmetros baratos, para os testes que não são sobre custo.
BARATA = Politica(ln=10, r=8, p=1)


def test_senha_certa_confere():
    h, p = hashear("segredo", BARATA)
    assert verificar("segredo", h, p) is True


def test_senha_errada_nao_confere():
    h, p = hashear("segredo", BARATA)
    assert verificar("outra", h, p) is False


def test_o_algoritmo_vem_primeiro_na_linha():
    """É o que permite validar pelo que a linha declara, não pela política."""
    _, p = hashear("x", BARATA)
    assert p.split("$")[0] == ALGORITMO
    assert p.startswith("scrypt$ln=10,r=8,p=1$")


def test_cada_hash_tem_salt_proprio():
    (h1, p1), (h2, p2) = hashear("igual", BARATA), hashear("igual", BARATA)
    assert p1 != p2
    assert h1 != h2


def test_algoritmo_desconhecido_falha_em_vez_de_cair_no_padrao():
    with pytest.raises(AlgoritmoDesconhecidoError) as erro:
        verificar("x", "AAAA", "argon2id$m=65536,t=3,p=4$c2FsdA==")
    assert "argon2id" in str(erro.value)


@pytest.mark.parametrize(
    "params",
    ["scrypt$ln=10,r=8", "so-uma-parte", "scrypt$ln=dez,r=8,p=1$c2FsdA==", ""],
)
def test_parametros_ilegiveis_falham(params):
    with pytest.raises((ParametrosIlegiveisError, AlgoritmoDesconhecidoError)):
        verificar("x", "AAAA", params)


# --------------------------------------------------------------------------
# Migração preguiçosa: o que mantém a porta aberta.
# --------------------------------------------------------------------------


def test_hash_com_parametros_antigos_continua_valendo():
    """Validar pelo que a linha declara, mesmo defasada."""
    antiga = Politica(ln=10, r=8, p=1)
    h, p = hashear("segredo", antiga)
    assert verificar("segredo", h, p) is True


def test_parametros_defasados_pedem_rehash():
    _, p = hashear("x", Politica(ln=10, r=8, p=1))
    assert precisa_de_rehash(p, Politica(ln=16, r=8, p=2)) is True


def test_parametros_na_politica_nao_pedem_rehash():
    _, p = hashear("x", BARATA)
    assert precisa_de_rehash(p, BARATA) is False


def test_subir_n_sem_trocar_algoritmo_tambem_pede_rehash():
    """O caso mais provável: mexer no custo, não no algoritmo."""
    _, p = hashear("x", Politica(ln=10, r=8, p=1))
    assert precisa_de_rehash(p, Politica(ln=11, r=8, p=1)) is True


def test_linha_ilegivel_nao_pede_rehash():
    """Não dá para re-hashear o que não dá para validar; quem valida decide."""
    assert precisa_de_rehash("argon2id$m=1$c2FsdA==") is False


# --------------------------------------------------------------------------
# A armadilha do maxmem: teste pequeno passa, produção real quebra.
# --------------------------------------------------------------------------


def test_a_politica_de_verdade_funciona():
    """Com os parâmetros que vão para produção, não com os baratos.

    Este teste custa 64 MiB e alguns décimos de segundo, e é justamente o que
    um teste com `ln=10` não provaria.
    """
    h, p = hashear("segredo", POLITICA)
    assert p.startswith("scrypt$ln=16,r=8,p=2$")
    assert verificar("segredo", h, p) is True


def test_o_maxmem_padrao_recusaria_a_politica():
    """Prova a armadilha, para ninguém "simplificar" o cálculo depois.

    `hashlib.scrypt` com `maxmem=0` usa o limite do OpenSSL, da ordem de
    32 MiB, e a política pede 64 MiB.
    """
    with pytest.raises(ValueError, match="memory limit exceeded"):
        hashlib.scrypt(b"x", salt=b"y", n=POLITICA.n, r=POLITICA.r, p=POLITICA.p, dklen=64)


def test_o_maxmem_calculado_basta():
    hashlib.scrypt(
        b"x",
        salt=b"y",
        n=POLITICA.n,
        r=POLITICA.r,
        p=POLITICA.p,
        maxmem=POLITICA.memoria(),
        dklen=64,
    )


def test_a_memoria_da_politica_e_a_da_rfc():
    """`128 * N * r` é o custo da RFC 7914; a folga é para `p` e cabeçalho."""
    assert POLITICA.memoria() >= 128 * POLITICA.n * POLITICA.r
    assert POLITICA.memoria() < 128 * POLITICA.n * POLITICA.r + 2**20


def test_a_politica_padrao_e_a_do_plano():
    assert (POLITICA.ln, POLITICA.r, POLITICA.p) == (16, 8, 2)
    assert POLITICA.memoria() // 2**20 == 64


def test_o_hash_tem_o_tamanho_declarado():
    h, _ = hashear("x", BARATA)
    assert len(base64.b64decode(h)) == 64
