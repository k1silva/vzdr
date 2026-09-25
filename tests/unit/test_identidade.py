"""Os tres nomes que o ciclo cria, e o que a reconciliacao le de volta.

O que estes testes protegem nao e formato de string: e a definicao de orfao. Se
`ler_nome` aceitar o que nao e nosso, a limpeza apaga recurso de cliente (P1); se
recusar o que e nosso, o orfao fica para sempre e o ciclo seguinte colide com ele.
"""

import re
from uuid import UUID, uuid4

import pytest

from vzdr.core.domain.identidade import (
    PREFIXO,
    Especie,
    NomeDeCiclo,
    NomeNossoIlegivel,
    ler_nome,
    nome_de,
    nome_do_bitmap,
    nome_do_checkpoint,
    nome_do_export,
)

TRES = (nome_do_bitmap, nome_do_checkpoint, nome_do_export)


@pytest.mark.parametrize("fabrica", TRES)
def test_deterministico(fabrica):
    """Mesmo ciclo, mesmo nome — em qualquer processo, em qualquer execucao.

    E o que permite o agente reencontrar o recurso depois de um reinicio sem ter
    guardado nada.
    """
    ciclo = uuid4()
    assert fabrica(ciclo) == fabrica(ciclo)


@pytest.mark.parametrize("fabrica", TRES)
def test_ciclos_diferentes_nunca_colidem(fabrica):
    nomes = {fabrica(uuid4()) for _ in range(500)}
    assert len(nomes) == 500


def test_as_tres_especies_de_um_ciclo_nao_colidem_entre_si():
    """O bitmap, o checkpoint e o export do MESMO ciclo sao tres nomes.

    Se dois coincidissem, derrubar o export apagaria o checkpoint — e a especie
    e justamente o que separa os espacos de nome.
    """
    ciclo = uuid4()
    assert len({fabrica(ciclo) for fabrica in TRES}) == 3


@pytest.mark.parametrize("fabrica", TRES)
def test_o_nome_devolve_o_ciclo(fabrica):
    ciclo = uuid4()
    lido = ler_nome(fabrica(ciclo))
    assert lido is not None
    assert lido.ciclo_id == ciclo


@pytest.mark.parametrize(
    ("fabrica", "especie"),
    [
        (nome_do_bitmap, Especie.BITMAP),
        (nome_do_checkpoint, Especie.CHECKPOINT),
        (nome_do_export, Especie.EXPORT),
    ],
)
def test_o_nome_devolve_a_especie(fabrica, especie):
    lido = ler_nome(fabrica(uuid4()))
    assert lido is not None
    assert lido.especie is especie


@pytest.mark.parametrize("fabrica", TRES)
def test_nada_de_tmp1_nem_de_timestamp(fabrica):
    """As duas formas do laboratorio, recusadas por construcao.

    `tmp1` colide no segundo ciclo; `dr-<timestamp>` colide se dois ciclos
    comecarem no mesmo segundo e nao carrega identidade nenhuma.
    """
    nome = fabrica(uuid4())
    assert nome != "tmp1"
    assert not re.fullmatch(r"dr-\d+", nome)
    assert nome.startswith(PREFIXO + "-")


@pytest.mark.parametrize("fabrica", TRES)
def test_caracteres_seguros_para_qmp_e_libvirt(fabrica):
    """O nome viaja para `block-export-add` e `checkpoint-create-as`.

    Minusculas, digitos e hifen: nada de espaco, aspas, barra ou acento, que sao
    o comeco de citacao mal formada em linha de comando ou em JSON de QMP.
    """
    assert re.fullmatch(r"[a-z0-9-]+", fabrica(uuid4()))


@pytest.mark.parametrize(
    "alheio",
    [
        "tmp1",
        "dr-1727280000",
        "backup",
        "",
        "vzdr",
        "vzdr-bmp",
        "vzdr-bmp-",
        # hex curto, hex longo, nao-hex
        "vzdr-bmp-" + "a" * 31,
        "vzdr-bmp-" + "a" * 33,
        "vzdr-bmp-" + "z" * 32,
        # prefixo parecido, mas nao o nosso
        "vzdrx-bmp-" + "a" * 32,
        "x-vzdr-bmp-" + "a" * 32,
        # lixo em volta
        "vzdr-bmp-" + "a" * 32 + "-extra",
        " vzdr-bmp-" + "a" * 32,
        # `\n` no fim: em Python o `$` casa antes da quebra de linha final, e nome
        # chega de saida de comando, que termina em `\n`. Este caso reprovou a
        # primeira versao do leitor.
        "vzdr-bmp-" + "a" * 32 + "\n",
        "vzdr-bmp-" + "a" * 32 + "\n\n",
        "vzdr-bmp-" + "a" * 32 + "\r\n",
    ],
)
def test_nome_que_nao_e_nosso_devolve_none(alheio):
    """`None`, nao excecao: nome alheio e o caso comum numa varredura.

    E a diferenca entre "orfao nosso, pode limpar" e "nao e nosso, nao toque" —
    que e P1, nao arrumacao.
    """
    assert ler_nome(alheio) is None


def test_especie_desconhecida_nao_e_none():
    """Nosso pela forma, especie que esta versao nao interpreta.

    Devolver `None` diria "nao e nosso, nao toque", e o custo esta no topo do
    modulo: orfao que fica para sempre, em silencio, e o ciclo seguinte colide.

    Sao tres estados porque a acao e diferente em cada um — colapsar este no
    primeiro e valor desconhecido virando padrao, que o ADR-0015 proibe.
    """
    ciclo = uuid4()
    lido = ler_nome(f"{PREFIXO}-xyz-{ciclo.hex}")
    assert isinstance(lido, NomeNossoIlegivel)
    assert lido.especie_crua == "xyz"
    assert lido.ciclo_id == ciclo


def test_especie_desconhecida_nao_e_confundida_com_conhecida():
    """Quem reconcilia decide por tipo, e os dois nao se misturam."""
    assert not isinstance(ler_nome(f"{PREFIXO}-xyz-{uuid4().hex}"), NomeDeCiclo)
    assert not isinstance(ler_nome(nome_do_bitmap(uuid4())), NomeNossoIlegivel)


def test_forma_alheia_continua_sendo_none_mesmo_com_tres_letras():
    """O que muda e a especie desconhecida COM forma nossa.

    Prefixo alheio continua `None`: a forma inteira e que diz se e nosso.
    """
    assert ler_nome("vzdrx-xyz-" + "a" * 32) is None
    assert ler_nome("xyz-" + "a" * 32) is None


def test_hex_maiusculo_nao_e_aceito():
    """Duas grafias mapeando para o mesmo ciclo quebrariam a definicao de orfao.

    "Orfao e nome cujo ciclo nao esta ativo" deixaria de ser definicao e viraria
    consulta com empate — e a limpeza teria que escolher entre dois nomes.
    """
    ciclo = uuid4()
    nome = nome_do_bitmap(ciclo)
    assert ler_nome(nome.upper()) is None
    assert ler_nome(nome) is not None


def test_ida_e_volta_de_qualquer_especie():
    ciclo = uuid4()
    for especie in Especie:
        lido = ler_nome(nome_de(especie, ciclo))
        assert lido is not None
        assert (lido.especie, lido.ciclo_id) == (especie, ciclo)


def test_tenant_nao_aparece_no_nome():
    """Tenant se diz uma vez, e nao e aqui.

    O ciclo sabe de quem e. Segunda expressao da mesma coisa pode discordar, e no
    nome ela ainda vazaria o tenant para quem le o hypervisor.
    """
    ciclo = UUID("00000000-0000-4000-8000-000000000001")
    nome = nome_do_bitmap(ciclo)
    assert nome == f"{PREFIXO}-bmp-{ciclo.hex}"
    assert nome.count("-") == 2
