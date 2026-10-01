"""Cobertura fase <-> efeito, nos dois sentidos, sobre os catalogos reais.

A varredura do envelope perguntava coisas sobre CADA efeito e nunca sobre o
CONJUNTO. Tres efeitos faltavam — o ponto de recuperacao, a retirada do export, a
remocao dos checkpoints anteriores — e o ciclo nao tinha como terminar. Foi achado
enumerando as fases a mao, que e o metodo que depende de alguem lembrar de fazer.
Estes testes fazem a proxima lacuna aparecer no build.

E a terceira aplicacao do mesmo padrao no repositorio: check_eventos.py nos dois
sentidos, a regra 3 do meta-checador, e esta.
"""

import pytest

from vzdr.core.domain.ciclo import EFEITOS_DA_FASE, Fase, abandono_deixa_residuo
from vzdr.core.domain.efeitos import (
    ConsultarNoDaVm,
    Efeito,
    EfeitoDeDisco,
    EfeitoDeVm,
    InventariarVm,
    _por_tipo,
)

CATALOGO = set(_por_tipo(Efeito).values())


@pytest.mark.parametrize("fase", list(Fase), ids=lambda f: f.value)
def test_toda_fase_emite_ao_menos_um_efeito(fase):
    """Fase que nao emite nada e fase que nao faz nada."""
    assert EFEITOS_DA_FASE.get(fase), fase


@pytest.mark.parametrize("efeito", sorted(CATALOGO, key=lambda c: c.TIPO), ids=lambda c: c.TIPO)
def test_todo_efeito_e_emitido_por_ao_menos_uma_fase(efeito):
    """O sentido que se esquece. Efeito que nenhuma fase emite e efeito morto — ou,
    o caso que mordeu, o ciclo tem um passo que nenhuma fase executa."""
    emitido = any(efeito in efeitos for efeitos in EFEITOS_DA_FASE.values())
    assert emitido, f"{efeito.TIPO} nao e emitido por fase nenhuma"


def test_a_tabela_so_nomeia_efeitos_que_existem():
    """E so fases que existem: chave estranha seria fase fantasma."""
    assert set(EFEITOS_DA_FASE) == set(Fase)
    for efeitos in EFEITOS_DA_FASE.values():
        assert set(efeitos) <= CATALOGO


def test_as_fases_de_leitura_sao_as_primeiras():
    """A validade do bitmap e decidida antes de qualquer trabalho caro. Na ordem
    da enumeracao, nenhuma fase com residuo vem antes de uma sem residuo, fora a
    de cercamento, que e da reconciliacao e nao do caminho normal."""
    normal = [f for f in Fase if f is not Fase.CERCANDO]
    residuos = [abandono_deixa_residuo(f) for f in normal]
    assert residuos == sorted(residuos), [
        (f.value, r) for f, r in zip(normal, residuos, strict=True)
    ]


@pytest.mark.parametrize("fase", [Fase.LOCALIZANDO, Fase.VALIDANDO], ids=lambda f: f.value)
def test_leitura_nao_deixa_residuo(fase):
    """Abandonar uma leitura so custa tempo — nenhum bitmap, checkpoint, export
    ou lease. E o que permite um prazo estourado ali virar "nunca iniciou"."""
    assert not abandono_deixa_residuo(fase)


@pytest.mark.parametrize("fase", list(Fase), ids=lambda f: f.value)
def test_residuo_e_derivado_dos_efeitos_e_nao_enumerado(fase):
    """A propriedade, e nao uma lista: fase deixa residuo sse algum efeito dela
    segura chave. Uma fase nova herda a resposta certa sem ninguem decidir."""
    toca_disco = any(issubclass(e, (EfeitoDeDisco, EfeitoDeVm)) for e in EFEITOS_DA_FASE[fase])
    assert abandono_deixa_residuo(fase) is toca_disco


def test_as_duas_leituras_esperam_partes_diferentes():
    """LOCALIZANDO espera o Nova; VALIDANDO espera o agente. Falham separado, e o
    operador precisa saber qual das duas parou — por isso sao duas fases."""
    assert ConsultarNoDaVm.ALVO is not InventariarVm.ALVO
