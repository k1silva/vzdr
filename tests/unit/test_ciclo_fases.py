"""Cobertura fase <-> efeito, nos dois sentidos, sobre os catalogos reais.

A varredura do envelope perguntava coisas sobre CADA efeito e nunca sobre o
CONJUNTO. Tres efeitos faltavam — o ponto de recuperacao, a retirada do export, a
remocao dos checkpoints anteriores — e o ciclo nao tinha como terminar. Foi achado
enumerando as fases a mao, que e o metodo que depende de alguem lembrar de fazer.
Estes testes fazem a proxima lacuna aparecer no build.

E a terceira aplicacao do mesmo padrao no repositorio: check_eventos.py nos dois
sentidos, a regra 3 do meta-checador, e esta.
"""

from itertools import combinations
from uuid import uuid4

import pytest

from vzdr.core.domain.ciclo import EFEITOS_DA_FASE, ETAPAS_DA_FASE, Fase, abandono_deixa_residuo
from vzdr.core.domain.efeitos import (
    Alvo,
    ConsultarNoDaVm,
    Efeito,
    EfeitoDeDisco,
    EfeitoDeVm,
    InventariarVm,
    _por_tipo,
    se_excluem,
)

CATALOGO = set(_por_tipo(Efeito).values())
VM = uuid4()
DISCOS = ("vda", "vdb")


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
    assert residuos == sorted(residuos), [(f.value, r) for f, r in zip(normal, residuos)]


@pytest.mark.parametrize("fase", [Fase.LOCALIZANDO, Fase.VALIDANDO], ids=lambda f: f.value)
def test_leitura_nao_deixa_residuo(fase):
    """Abandonar uma leitura so custa tempo — nenhum bitmap, checkpoint, export
    ou lease. Sobre a FASE: se um prazo ali vira "nunca iniciou" depende do
    caminho do ciclo, que e `ja_deixou_residuo` (T5), e nao desta resposta."""
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


def _instancias(classe):
    """Uma ocorrencia por disco de uma VM de dois discos, como a fase as emitiria."""
    base = {
        "tenant_id": uuid4(),
        "ciclo_id": uuid4(),
        "vm_id": VM,
        "no": "no-1" if classe.ALVO is Alvo.AGENTE_DE_ORIGEM else None,
    }
    if issubclass(classe, EfeitoDeVm):
        return [classe(**base, discos=DISCOS)]
    if issubclass(classe, EfeitoDeDisco):
        return [classe(**base, disco=d) for d in DISCOS]
    return [classe(**base)]


def _efeitos_se_excluem_entre_si(fase):
    ocorrencias = [o for classe in EFEITOS_DA_FASE[fase] for o in _instancias(classe)]
    return any(se_excluem(a, b) for a, b in combinations(ocorrencias, 2))


def test_liberando_e_a_unica_fase_cujos_efeitos_se_excluem_entre_si():
    """Onde os efeitos de uma fase se excluem, a transicao dela nao pode ser
    "emite todos e espera todos": e ordenada, e alguem tem que escolher a ordem.
    Derivado de `se_excluem` sobre ocorrencias reais, e nao de uma lista — uma fase
    nova nessa condicao reprova aqui, e quem a criou decide a ordem na hora, em
    vez de descobri-la escrevendo `avancar`."""
    ordenadas = {f for f in Fase if _efeitos_se_excluem_entre_si(f)}
    assert ordenadas == {Fase.LIBERANDO}, sorted(f.value for f in ordenadas)


@pytest.mark.parametrize("fase", list(Fase), ids=lambda f: f.value)
def test_dentro_de_uma_etapa_nada_se_exclui(fase):
    """E o que torna seguro pedir uma etapa inteira de uma vez. O que se exclui vai
    em etapas diferentes, e a ordem entre elas e a da tabela."""
    for etapa in ETAPAS_DA_FASE[fase]:
        ocorrencias = [o for classe in etapa for o in _instancias(classe)]
        juntos = [(a.TIPO, b.TIPO) for a, b in combinations(ocorrencias, 2) if se_excluem(a, b)]
        assert juntos == [], juntos
