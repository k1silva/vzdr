"""O envelope do efeito, e o que ele promete a quem nunca vai abri-lo.

Estes testes nao exercitam comportamento de ciclo — isso e da T5 em diante. O que
esta aqui e o CONTRATO: o que a fila, o despachante e a reconciliacao leem sem
saber o que o efeito significa, e o que acontece quando chega algo que esta
versao nao conhece.
"""

import dataclasses
import json
from uuid import uuid4

import pytest

from vzdr.core.domain.efeitos import (
    PREEMPCAO_DESPEJA_DETENTOR,
    Alvo,
    CercarDestino,
    ChaveDeExclusao,
    ConfirmarNoDestino,
    ConsultarNoDaVm,
    CriarCheckpoint,
    DescartarBitmap,
    Efeito,
    EfeitoDeDisco,
    EfeitoDePreempcao,
    IniciarCopia,
    InventariarHypervisor,
    PublicarExport,
    Resultado,
    ResultadoDeCopia,
    ResultadoDeInventario,
    ResultadoDeLocalizacao,
    ResultadoSimples,
    ValorDesconhecidoError,
    efeito_de_json,
    pode_tomar_chave_tomada,
    resultado_de_json,
)

TENANT = uuid4()
CICLO = uuid4()
VM = uuid4()

DE_DISCO = (
    CriarCheckpoint,
    IniciarCopia,
    DescartarBitmap,
    PublicarExport,
    ConfirmarNoDestino,
    CercarDestino,
)
SEM_DISCO = (InventariarHypervisor, ConsultarNoDaVm)


def um(classe, **troca):
    base = {"tenant_id": TENANT, "ciclo_id": CICLO}
    if issubclass(classe, EfeitoDeDisco):
        base.update(vm_id=VM, disco="vda")
    base.update(troca)
    return classe(**base)


TODOS = [um(c) for c in DE_DISCO + SEM_DISCO]


# ── Propriedade 1: o efeito e serializavel ──────────────────────────────────


@pytest.mark.parametrize("efeito", TODOS, ids=lambda e: e.TIPO)
def test_ida_e_volta(efeito):
    """Entre pedir e fazer existem uma fila e uma rede.

    Efeito que nao cabe numa linha nao sobrevive a fila, e o agente busca
    trabalho depois, de outro processo, talvez apos um reinicio.
    """
    assert efeito_de_json(json.loads(json.dumps(efeito.para_json()))) == efeito


@pytest.mark.parametrize("efeito", TODOS, ids=lambda e: e.TIPO)
def test_cabe_em_json_de_verdade(efeito):
    """`json.dumps` sem `default=`: nada de UUID cru nem de enum solto."""
    assert isinstance(json.dumps(efeito.para_json()), str)


# ── Propriedade 3: ciclo_id em todo efeito ──────────────────────────────────


@pytest.mark.parametrize("efeito", TODOS, ids=lambda e: e.TIPO)
def test_ciclo_id_viaja(efeito):
    """Sem ele, resultado atrasado do ciclo N e aceito como do N+1 — e uma
    janela que nao foi copiada e dada por concluida, sem erro e sem alarme."""
    assert efeito.para_json()["ciclo_id"] == str(CICLO)


def test_efeito_sem_ciclo_id_nao_existe():
    with pytest.raises(TypeError):
        CriarCheckpoint(tenant_id=TENANT, vm_id=VM, disco="vda")


# ── Propriedade 4: chave de exclusao ────────────────────────────────────────


@pytest.mark.parametrize("classe", DE_DISCO, ids=lambda c: c.TIPO)
def test_efeito_de_disco_sem_chave_nao_chega_a_existir(classe):
    with pytest.raises(TypeError):
        classe(tenant_id=TENANT, ciclo_id=CICLO)


def test_mesmo_disco_mesma_chave_mesmo_em_ciclos_diferentes():
    """O `ciclo_id` NAO entra na chave, e isso e o ponto.

    Se entrasse, dois ciclos sobre o mesmo disco teriam chaves diferentes e
    poderiam escrever juntos — exatamente o que a chave existe para impedir.
    """
    a = um(IniciarCopia)
    b = um(IniciarCopia, ciclo_id=uuid4())
    assert a.chave_de_exclusao() == b.chave_de_exclusao()


def test_discos_diferentes_chaves_diferentes():
    """Multi-disco copia em paralelo; a exclusao e por disco, nao por VM."""
    assert um(IniciarCopia).chave_de_exclusao() != um(IniciarCopia, disco="vdb").chave_de_exclusao()


def test_dois_efeitos_do_mesmo_ciclo_sobre_o_mesmo_disco_colidem():
    """Os dois em conflito sao do MESMO ciclo — o original e o reemitido depois
    que o lease caiu. E por isso que o `ciclo_id` nao resolve isto."""
    assert um(IniciarCopia).chave_de_exclusao() == um(ConfirmarNoDestino).chave_de_exclusao()


@pytest.mark.parametrize(
    "efeito", [e for e in TODOS if isinstance(e, EfeitoDeDisco)], ids=lambda e: e.TIPO
)
def test_a_chave_sobrevive_a_serializacao(efeito):
    """A fila so le o que o valor carrega."""
    assert efeito_de_json(efeito.para_json()).chave_de_exclusao() == efeito.chave_de_exclusao()


def test_efeito_sem_disco_nao_tem_chave():
    """Inventariar e consultar o Nova nao escrevem nada; exigir chave deles
    faria a exclusao bloquear leitura."""
    assert not hasattr(um(InventariarHypervisor), "chave_de_exclusao")


# ── Preempcao ───────────────────────────────────────────────────────────────


def test_so_preempcao_toma_chave_tomada():
    assert pode_tomar_chave_tomada(um(CercarDestino))
    for efeito in TODOS:
        if not isinstance(efeito, EfeitoDePreempcao):
            assert not pode_tomar_chave_tomada(efeito), efeito.TIPO


def test_preempcao_coexiste_e_nao_despeja():
    """Preempcao nao precisa de exclusividade: precisa de permissao para agir
    apesar da chave. Exclusividade existe para impedir dois escritores, e
    preempcao nao e escritor.

    Despejar deixaria um `CercarDestino` reentregue por retry, depois de o ciclo
    N ter fechado, derrubar o lease do N+1 — que esta copiando.
    """
    assert PREEMPCAO_DESPEJA_DETENTOR is False


def test_preempcao_repetida_e_o_mesmo_valor():
    """Idempotente por construcao: a segunda tentativa encontra o export ja
    derrubado, e isso e sucesso, nao erro. Dois pedidos iguais sao um valor
    igual, entao a fila pode desduplicar sem saber o que eles significam."""
    assert um(CercarDestino) == um(CercarDestino)


# ── Alvo, por modo de falha ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("classe", "alvo"),
    [
        (CriarCheckpoint, Alvo.AGENTE_DE_ORIGEM),
        (IniciarCopia, Alvo.AGENTE_DE_ORIGEM),
        (DescartarBitmap, Alvo.AGENTE_DE_ORIGEM),
        (InventariarHypervisor, Alvo.AGENTE_DE_ORIGEM),
        (PublicarExport, Alvo.RECEPTORA),
        (ConfirmarNoDestino, Alvo.RECEPTORA),
        (CercarDestino, Alvo.RECEPTORA),
        (ConsultarNoDaVm, Alvo.API_DA_NUVEM_DE_ORIGEM),
    ],
)
def test_cada_efeito_no_seu_alvo(classe, alvo):
    assert um(classe).alvo is alvo


def test_a_consulta_ao_nova_nao_e_do_agente():
    """O teste que uma enumeracao de dois valores reprovaria.

    A evidencia do no existe para o caso em que o agente NAO responde. Se ela
    caisse em "origem" e fosse entregue a um agente daquele hypervisor, morreria
    no unico cenario em que serve — e um no morto bloquearia aquele disco para
    sempre.
    """
    assert um(ConsultarNoDaVm).alvo is not um(InventariarHypervisor).alvo


@pytest.mark.parametrize("efeito", TODOS, ids=lambda e: e.TIPO)
def test_o_alvo_sobrevive_a_serializacao(efeito):
    assert efeito.para_json()["alvo"] == efeito.alvo.value


def test_alvo_nao_e_campo_de_instancia():
    """Como campo, `CercarDestino(alvo=AGENTE_DE_ORIGEM)` seria construtivel.

    O alvo e propriedade da ESPECIE, nao da ocorrencia, e o tipo pode
    simplesmente nao permitir o erro.
    """
    assert "alvo" not in {c.name for c in dataclasses.fields(CercarDestino)}


# ── Valor desconhecido recusa; campo desconhecido nao ───────────────────────


def test_campo_desconhecido_e_ignorado():
    """Evolucao aditiva: campo novo e opcional e nunca muda significado. E o
    que permite a versao do contrato nao ser campo."""
    dados = um(IniciarCopia).para_json()
    dados["limite_de_banda"] = 42
    assert efeito_de_json(dados) == um(IniciarCopia)


def test_alvo_desconhecido_recusa():
    """Precedente no `ler_nome`, em identidade.py: la a especie desconhecida
    vira um terceiro estado em vez de virar "nao e nosso". Mesma regra, dois
    modulos — cair num padrao aqui e rotear errado."""
    dados = um(IniciarCopia).para_json()
    dados["alvo"] = "api_da_nuvem_de_destino"
    with pytest.raises(ValorDesconhecidoError, match="alvo"):
        efeito_de_json(dados)


def test_tipo_de_efeito_desconhecido_recusa():
    """Categoria desconhecida: pode ser um agente mais novo no mesmo parque."""
    dados = um(IniciarCopia).para_json()
    dados["tipo"] = "cercar_origem"
    with pytest.raises(ValorDesconhecidoError, match="tipo de efeito"):
        efeito_de_json(dados)


def test_alvo_que_contradiz_o_tipo_recusa():
    """Contradicao nao se resolve escolhendo um dos dois lados."""
    dados = um(CercarDestino).para_json()
    dados["alvo"] = Alvo.AGENTE_DE_ORIGEM.value
    with pytest.raises(ValorDesconhecidoError, match="alvo"):
        efeito_de_json(dados)


def test_tipo_de_resultado_desconhecido_recusa():
    dados = ResultadoSimples(tenant_id=TENANT, ciclo_id=CICLO, tipo_do_efeito="x").para_json()
    dados["tipo"] = "telepatia"
    with pytest.raises(ValorDesconhecidoError):
        resultado_de_json(dados)


# ── Tenant se diz uma vez ───────────────────────────────────────────────────


@pytest.mark.parametrize("efeito", TODOS, ids=lambda e: e.TIPO)
def test_nenhum_efeito_serializado_repete_tenant(efeito):
    """Com RLS, segunda expressao de tenant vira oraculo de existencia: um id
    no corpo apontando para linha de outro tenant responde o que a politica
    esconde. E o que o ADR-0006 ja tratou.
    """
    bruto = json.dumps(efeito.para_json())
    assert bruto.count(str(TENANT)) == 1
    achatado = json.dumps(efeito.para_json())
    assert "projeto" not in achatado and "tenant" not in achatado.replace("tenant_id", "")


# ── Resultados ──────────────────────────────────────────────────────────────

RESULTADOS = [
    ResultadoSimples(tenant_id=TENANT, ciclo_id=CICLO, tipo_do_efeito="descartar_bitmap"),
    ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="cercar_destino",
        chave=ChaveDeExclusao(vm_id=VM, disco="vda"),
        sucesso=False,
        motivo="export ja nao existia",
    ),
    ResultadoDeCopia(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="iniciar_copia",
        chave=ChaveDeExclusao(vm_id=VM, disco="vda"),
        bytes_transferidos=17_510_400,
        concluido=True,
    ),
    ResultadoDeInventario(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="inventariar_hypervisor",
        job_em_curso=True,
        nomes_encontrados=("vzdr-bmp-" + "a" * 32,),
    ),
    ResultadoDeLocalizacao(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="consultar_no_da_vm",
        no_atual="node-02",
    ),
]


@pytest.mark.parametrize("resultado", RESULTADOS, ids=lambda r: f"{r.TIPO}-{r.tipo_do_efeito}")
def test_resultado_ida_e_volta(resultado):
    assert resultado_de_json(json.loads(json.dumps(resultado.para_json()))) == resultado


def test_resultado_sem_ciclo_id_nao_existe():
    with pytest.raises(TypeError):
        ResultadoSimples(tenant_id=TENANT, tipo_do_efeito="x")


def test_resultado_repetido_e_o_mesmo_valor():
    """Tolerar repeticao comeca aqui: o agente pode reportar duas vezes — rede
    que cai entre concluir e reportar, retry, reinicio no meio do reporte. Dois
    reportes iguais tem que ser indistinguiveis, senao quem absorve nao tem como
    desduplicar. O que a maquina FAZ com a repeticao e da T6.
    """
    a, b = RESULTADOS[2], dataclasses.replace(RESULTADOS[2])
    assert a == b and a.para_json() == b.para_json()


def test_resultado_correlaciona_sem_id_proprio():
    """Nao ha id de efeito, e isso e decisao, nao esquecimento.

    A correlacao e a tripla que ja viaja — ciclo, tipo do efeito e, nos de
    disco, a chave. Dois efeitos do mesmo tipo, do mesmo ciclo, sobre o mesmo
    disco nao podem estar pendentes juntos: e o que a chave garante. Id novo
    seria segunda forma de dizer a mesma coisa.
    """
    efeito = um(IniciarCopia)
    resultado = RESULTADOS[2]
    assert resultado.ciclo_id == efeito.ciclo_id
    assert resultado.tipo_do_efeito == efeito.TIPO
    assert resultado.chave == efeito.chave_de_exclusao()


def test_resultado_de_efeito_sem_disco_nao_carrega_chave():
    assert RESULTADOS[3].chave is None
    assert "chave" not in RESULTADOS[3].para_json()


# ── O envelope e fechado ────────────────────────────────────────────────────


def test_o_envelope_tem_exatamente_os_campos_da_varredura():
    """A varredura decidiu quatro campos e sete nao-campos, com motivo.

    Este teste e onde um quinto campo encosta: quem acrescentar tem que dizer
    por que ele nao estava na tabela do plano. Sem isto, o envelope volta a
    crescer de emenda em emenda, que foi o que a varredura fechou.
    """
    assert {c.name for c in dataclasses.fields(Efeito)} == {"tenant_id", "ciclo_id"}
    assert {c.name for c in dataclasses.fields(EfeitoDeDisco)} == {
        "tenant_id",
        "ciclo_id",
        "vm_id",
        "disco",
    }


def test_todo_efeito_declara_tipo_e_alvo():
    """Tipo repetido faria dois efeitos diferentes lerem como o mesmo."""
    concretos = [type(e) for e in TODOS]
    tipos = [c.TIPO for c in concretos]
    assert len(set(tipos)) == len(tipos)
    assert all(isinstance(c.ALVO, Alvo) for c in concretos)


def test_todo_resultado_declara_tipo_unico():
    tipos = [type(r).TIPO for r in RESULTADOS]
    assert len(set(tipos)) == len({type(r) for r in RESULTADOS})
    assert all(isinstance(r, Resultado) for r in RESULTADOS)
