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
    CatalogoAmbiguoError,
    CercarDestino,
    ChaveDeExclusao,
    ConfirmarNoDestino,
    ConsultarNoDaVm,
    DescartarBitmap,
    Efeito,
    EfeitoDeDisco,
    EfeitoDePreempcao,
    EfeitoDeVm,
    FecharJanela,
    IniciarCopia,
    InventariarVm,
    PublicarExport,
    RegistroMalformadoError,
    Resultado,
    ResultadoDeCopia,
    ResultadoDeInventario,
    ResultadoDeLocalizacao,
    ResultadoSimples,
    ResultadoVmAusente,
    ValorDesconhecidoError,
    _por_tipo,
    chaves_de,
    efeito_de_json,
    pode_tomar_chave_tomada,
    responde_a,
    resultado_de_json,
    se_excluem,
)

TENANT = uuid4()
CICLO = uuid4()
VM = uuid4()

DE_DISCO = (
    IniciarCopia,
    DescartarBitmap,
    PublicarExport,
    ConfirmarNoDestino,
    CercarDestino,
)
DE_VM = (FecharJanela,)
SEM_DISCO = (InventariarVm, ConsultarNoDaVm)


NO = "no-01"


def um(classe, **troca):
    no = NO if classe.ALVO is Alvo.AGENTE_DE_ORIGEM else None
    base = {"tenant_id": TENANT, "ciclo_id": CICLO, "vm_id": VM, "no": no}
    if issubclass(classe, EfeitoDeDisco):
        base.update(disco="vda")
    elif issubclass(classe, EfeitoDeVm):
        base.update(discos=("vda", "vdb"))
    base.update(troca)
    return classe(**base)


TODOS = [um(c) for c in DE_DISCO + DE_VM + SEM_DISCO]


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
        IniciarCopia(tenant_id=TENANT, vm_id=VM, disco="vda")


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
    assert a.chaves_de_exclusao() == b.chaves_de_exclusao()


def test_discos_diferentes_chaves_diferentes():
    """Multi-disco copia em paralelo; a exclusao e por disco, nao por VM."""
    assert (
        um(IniciarCopia).chaves_de_exclusao() != um(IniciarCopia, disco="vdb").chaves_de_exclusao()
    )


def test_dois_efeitos_do_mesmo_ciclo_sobre_o_mesmo_disco_colidem():
    """Os dois em conflito sao do MESMO ciclo — o original e o reemitido depois
    que o lease caiu. E por isso que o `ciclo_id` nao resolve isto."""
    assert um(IniciarCopia).chaves_de_exclusao() == um(ConfirmarNoDestino).chaves_de_exclusao()


@pytest.mark.parametrize(
    "efeito", [e for e in TODOS if isinstance(e, EfeitoDeDisco)], ids=lambda e: e.TIPO
)
def test_a_chave_sobrevive_a_serializacao(efeito):
    """A fila so le o que o valor carrega."""
    assert efeito_de_json(efeito.para_json()).chaves_de_exclusao() == efeito.chaves_de_exclusao()


def test_efeito_sem_disco_nao_tem_chave():
    """Inventariar e consultar o Nova nao escrevem nada; exigir chave deles
    faria a exclusao bloquear leitura."""
    assert chaves_de(um(InventariarVm)) == ()


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
        (FecharJanela, Alvo.AGENTE_DE_ORIGEM),
        (IniciarCopia, Alvo.AGENTE_DE_ORIGEM),
        (DescartarBitmap, Alvo.AGENTE_DE_ORIGEM),
        (InventariarVm, Alvo.AGENTE_DE_ORIGEM),
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
    assert um(ConsultarNoDaVm).alvo is not um(InventariarVm).alvo


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
    with pytest.raises(RegistroMalformadoError, match="alvo"):
        efeito_de_json(dados)


def test_tipo_de_resultado_desconhecido_recusa():
    dados = ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="x",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(),
        sucesso=True,
    ).para_json()
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
    ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="descartar_bitmap",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(ChaveDeExclusao(vm_id=VM, disco="vda"),),
        sucesso=True,
    ),
    ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="cercar_destino",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(ChaveDeExclusao(vm_id=VM, disco="vda"),),
        sucesso=False,
        motivo="export ja nao existia",
    ),
    ResultadoDeCopia(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="iniciar_copia",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(ChaveDeExclusao(vm_id=VM, disco="vda"),),
        bytes_transferidos=17_510_400,
        concluido=True,
    ),
    ResultadoDeInventario(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="inventariar_vm",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(),
        job_em_curso=True,
        nomes_encontrados=("vzdr-bmp-" + "a" * 32,),
    ),
    ResultadoDeLocalizacao(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="consultar_no_da_vm",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(),
        no_atual="node-02",
    ),
    ResultadoVmAusente(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="inventariar_vm",
        vm_id=VM,
        no_que_respondeu="no-01",
        chaves=(),
    ),
]


def _do_efeito(tipo_do_efeito):
    """A amostra que responde a um tipo de efeito — escolhida pelo que ela e, e nao
    pela posicao na lista."""
    return next(r for r in RESULTADOS if r.tipo_do_efeito == tipo_do_efeito)


def _com_chave():
    return next(r for r in RESULTADOS if r.chaves)


@pytest.mark.parametrize("resultado", RESULTADOS, ids=lambda r: f"{r.TIPO}-{r.tipo_do_efeito}")
def test_resultado_ida_e_volta(resultado):
    assert resultado_de_json(json.loads(json.dumps(resultado.para_json()))) == resultado


def test_resultado_sem_ciclo_id_nao_existe():
    with pytest.raises(TypeError):
        ResultadoSimples(
            tenant_id=TENANT,
            tipo_do_efeito="x",
            vm_id=VM,
            no_que_respondeu=None,
            chaves=(),
            sucesso=True,
        )


def test_silencio_nao_pode_significar_sucesso():
    """`sucesso` sem padrao, e `concluido` tambem.

    Para um tipo cujo trabalho e relatar desfecho, construir sem dizer o desfecho
    nao pode dar "deu certo". A causa raiz era o padrao da `chave` na base, que
    obrigava toda subclasse a ter padrao — tirado ele, os dois voltaram a ser
    obrigatorios.
    """
    with pytest.raises(TypeError):
        ResultadoSimples(
            tenant_id=TENANT,
            ciclo_id=CICLO,
            tipo_do_efeito="x",
            vm_id=VM,
            no_que_respondeu=None,
            chaves=(),
        )
    with pytest.raises(TypeError):
        ResultadoDeCopia(
            tenant_id=TENANT,
            ciclo_id=CICLO,
            tipo_do_efeito="x",
            vm_id=VM,
            no_que_respondeu=None,
            chaves=(),
            bytes_transferidos=0,
        )


def test_resultado_repetido_e_o_mesmo_valor():
    """Tolerar repeticao comeca aqui: o agente pode reportar duas vezes — rede
    que cai entre concluir e reportar, retry, reinicio no meio do reporte. Dois
    reportes iguais tem que ser indistinguiveis, senao quem absorve nao tem como
    desduplicar. O que a maquina FAZ com a repeticao e da T6.
    """
    for a in RESULTADOS:
        b = dataclasses.replace(a)
        assert a == b and a.para_json() == b.para_json()


def test_resultado_correlaciona_sem_id_proprio():
    """Nao ha id de efeito, e isso e decisao, nao esquecimento.

    A correlacao e a tripla que ja viaja — ciclo, tipo do efeito e, nos de
    disco, a chave. Dois efeitos do mesmo tipo, do mesmo ciclo, sobre o mesmo
    disco nao podem estar pendentes juntos: e o que a chave garante. Id novo
    seria segunda forma de dizer a mesma coisa.
    """
    efeito = um(IniciarCopia)
    resultado = _do_efeito("iniciar_copia")
    assert resultado.ciclo_id == efeito.ciclo_id
    assert resultado.tipo_do_efeito == efeito.TIPO
    assert resultado.chaves == efeito.chaves_de_exclusao()


def test_resultado_de_efeito_sem_disco_nao_carrega_chave():
    inventario = _do_efeito("inventariar_vm")
    assert inventario.chaves == ()
    assert inventario.para_json()["chaves"] == []


# ── O envelope e fechado ────────────────────────────────────────────────────


def test_o_envelope_tem_exatamente_os_campos_da_varredura():
    """A varredura decidiu quatro campos e sete nao-campos, com motivo.

    Este teste e onde um quinto campo encosta: quem acrescentar tem que dizer
    por que ele nao estava na tabela do plano. Sem isto, o envelope volta a
    crescer de emenda em emenda, que foi o que a varredura fechou.
    """
    # Segundo caso de "campo novo depois", e o motivo de nao estarem na tabela: a
    # varredura perguntou o que o despachante le, e NUNCA perguntou se o efeito tem
    # sujeito. `vm_id` diz sobre o que o efeito e; `no` diz onde o efeito de agente
    # roda, porque agentes de nos diferentes falham separado e o Alvo e por modo
    # de falha.
    envelope = {"tenant_id", "ciclo_id", "vm_id", "no"}
    assert {c.name for c in dataclasses.fields(Efeito)} == envelope
    assert {c.name for c in dataclasses.fields(EfeitoDeDisco)} == envelope | {"disco"}
    # O primeiro caso de "campo novo depois", e o motivo de ele nao estar na
    # tabela: a varredura perguntou O QUE a fila le, e nao DE QUANTOS DISCOS.
    # Checkpoint e congelamento sao da VM, e feitos disco a disco dariam um
    # instante por disco.
    assert {c.name for c in dataclasses.fields(EfeitoDeVm)} == envelope | {"discos"}


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


# ── O corpo do resultado e convertido, nao copiado ──────────────────────────


def _simples(**troca):
    base = {
        "tipo": "simples",
        "tenant_id": str(TENANT),
        "ciclo_id": str(CICLO),
        "tipo_do_efeito": "iniciar_copia",
        "vm_id": str(VM),
        "no_que_respondeu": None,
        "chaves": [],
        "sucesso": True,
        "motivo": None,
    }
    base.update(troca)
    return base


def test_texto_no_lugar_de_booleano_recusa():
    """O caso concreto: `"false"` e VERDADEIRO em Python.

    Copiado cru, um efeito que falhou era absorvido como sucesso — sem erro, sem
    alarme, e com o desfecho invertido.
    """
    with pytest.raises(RegistroMalformadoError, match="booleano"):
        resultado_de_json(_simples(sucesso="false"))


def test_copia_nao_concluida_nao_vira_concluida():
    """Pior que o anterior: janela dada por copiada sem ter sido.

    E o defeito que o `ciclo_id` existe para impedir, entrando por outra porta.
    """
    dados = {
        "tipo": "copia",
        "tenant_id": str(TENANT),
        "ciclo_id": str(CICLO),
        "tipo_do_efeito": "iniciar_copia",
        "vm_id": str(VM),
        "no_que_respondeu": None,
        "chaves": [{"vm_id": str(VM), "disco": "vda"}],
        "bytes_transferidos": 1,
        "concluido": "false",
    }
    with pytest.raises(RegistroMalformadoError, match="booleano"):
        resultado_de_json(dados)


def test_numero_em_texto_recusa():
    """Entra na telemetria e quebra a soma depois, longe daqui."""
    dados = {
        "tipo": "copia",
        "tenant_id": str(TENANT),
        "ciclo_id": str(CICLO),
        "tipo_do_efeito": "iniciar_copia",
        "vm_id": str(VM),
        "no_que_respondeu": None,
        "chaves": [],
        "bytes_transferidos": "17510400",
        "concluido": True,
    }
    with pytest.raises(RegistroMalformadoError, match="inteiro"):
        resultado_de_json(dados)


def test_booleano_nao_passa_por_inteiro():
    """`isinstance(True, int)` e verdadeiro em Python, entao isto precisa de
    recusa a mao — senao `True` entra como 1 na telemetria."""
    dados = {
        "tipo": "copia",
        "tenant_id": str(TENANT),
        "ciclo_id": str(CICLO),
        "tipo_do_efeito": "iniciar_copia",
        "vm_id": str(VM),
        "no_que_respondeu": None,
        "chaves": [],
        "bytes_transferidos": True,
        "concluido": True,
    }
    with pytest.raises(RegistroMalformadoError, match="inteiro"):
        resultado_de_json(dados)


def test_campo_obrigatorio_ausente_recusa():
    dados = _simples()
    del dados["sucesso"]
    with pytest.raises(RegistroMalformadoError, match="obrigatorio"):
        resultado_de_json(dados)


def test_texto_no_lugar_de_lista_recusa():
    """Texto e iteravel, e iterar sobre ele daria uma lista de letras."""
    dados = {
        "tipo": "inventario",
        "tenant_id": str(TENANT),
        "ciclo_id": str(CICLO),
        "tipo_do_efeito": "inventariar_vm",
        "vm_id": str(VM),
        "no_que_respondeu": None,
        "chaves": [],
        "job_em_curso": False,
        "nomes_encontrados": "vzdr-bmp-x",
    }
    with pytest.raises(RegistroMalformadoError, match="lista de texto"):
        resultado_de_json(dados)


def test_campo_desconhecido_no_resultado_continua_ignorado():
    """A recusa e de VALOR; campo novo continua aditivo."""
    lido = resultado_de_json(_simples(velocidade_media=3))
    assert lido.sucesso is True


# ── Correlacao: tres classes, tres razoes ───────────────────────────────────


def test_dois_cercamentos_do_mesmo_ciclo_e_disco_sao_iguais():
    """A chave NAO garante unicidade para preempcao — ela toma chave tomada e
    coexiste. Dois `CercarDestino` do mesmo ciclo e disco podem ficar pendentes
    juntos, pelo caminho de reentrega por retry.

    E inofensivo porque preempcao e idempotente, e isso e obrigacao e nao
    coincidencia: dois pedidos iguais sao o mesmo valor, e dois resultados iguais
    tambem.
    """
    assert um(CercarDestino) == um(CercarDestino)
    a = ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="cercar_destino",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(ChaveDeExclusao(vm_id=VM, disco="vda"),),
        sucesso=True,
    )
    assert a == dataclasses.replace(a)


def test_efeito_sem_chave_tambem_depende_de_idempotencia():
    """`InventariarVm` e `ConsultarNoDaVm` nao tem chave nenhuma.

    Nada impede dois pendentes; e inofensivo porque sao leituras, e leitura
    repetida devolve o mesmo valor.
    """
    assert um(InventariarVm) == um(InventariarVm)
    b = ResultadoDeLocalizacao(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="consultar_no_da_vm",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(),
        no_atual="node-02",
    )
    assert b == dataclasses.replace(b)


# ── Catalogo ────────────────────────────────────────────────────────────────


def test_tipo_duplicado_levanta():
    """A ultima classe visitada venceria em silencio, e a ordem de visita vem de
    `pop()` sobre `__subclasses__()` — nao e estavel nem previsivel. Com duas
    classes disputando a mesma string, `efeito_de_json` construiria o tipo ERRADO
    a partir de um JSON valido.

    E `CatalogoAmbiguoError`, nao registro malformado nem valor desconhecido: o
    defeito e desta versao do codigo, nao da mensagem. Reenviar entraria em laco;
    descartar jogaria fora registro valido.

    A hierarquia e propria do teste, e nao a real. A versao anterior criava uma
    subclasse impostora de `IniciarCopia`; quando a excecao esperada deixou de
    bater, o traceback segurou a classe viva e envenenou o catalogo de todos os
    testes seguintes do arquivo — uma falha virou cascata.
    """

    class Raiz:
        pass

    class Primeira(Raiz):
        TIPO = "repetido"

    class Segunda(Raiz):
        TIPO = "repetido"

    with pytest.raises(CatalogoAmbiguoError, match="duas classes"):
        _por_tipo(Raiz)


def test_as_tres_excecoes_nao_se_capturam_umas_as_outras():
    """O TIPO da excecao decide a acao de quem trata, e as acoes sao opostas:
    reenviar, descartar, parar. Se uma herdasse de outra, o `except` de uma
    capturaria a outra, e o despachante reenviaria para sempre um registro
    quebrado — o laco que nao termina, com outra roupa."""
    tres = (ValorDesconhecidoError, RegistroMalformadoError, CatalogoAmbiguoError)
    for a in tres:
        for b in tres:
            if a is not b:
                assert not issubclass(a, b), (a, b)


# ── A chave exige, nao coage ────────────────────────────────────────────────


def test_disco_que_nao_e_texto_recusa():
    """O campo que guarda P1 e P2 e o ultimo lugar para coagir.

    Com `str(...)`, um `42` virava `"42"` e a chave reconstruida deixava de ser a
    chave que a maquina criou. Dois efeitos que deveriam colidir passavam a nao
    colidir, e a exclusao deixava de excluir — sem erro, com a forma toda certa.
    """
    dados = um(IniciarCopia).para_json()
    dados["chaves_de_exclusao"][0]["disco"] = 42
    with pytest.raises(RegistroMalformadoError, match="disco"):
        efeito_de_json(dados)


@pytest.mark.parametrize("campo", ["tenant_id", "ciclo_id"])
def test_uuid_do_envelope_que_nao_e_texto_recusa_com_o_tipo_certo(campo):
    """Falhava fechado antes, mas com `ValueError` cru.

    Quem trata "contrato mais novo que eu" pega `ValorDesconhecidoError`. Falha
    fechada com o tipo errado vira excecao nao tratada no despachante.
    """
    dados = um(IniciarCopia).para_json()
    dados[campo] = 42
    with pytest.raises(RegistroMalformadoError, match=campo):
        efeito_de_json(dados)


def test_vm_id_que_nao_e_uuid_recusa_com_o_tipo_certo():
    dados = um(IniciarCopia).para_json()
    dados["chaves_de_exclusao"][0]["vm_id"] = "nao-e-uuid"
    with pytest.raises(RegistroMalformadoError, match="vm_id"):
        efeito_de_json(dados)


@pytest.mark.parametrize("campo", ["tenant_id", "ciclo_id", "tipo_do_efeito"])
def test_campo_do_envelope_ausente_recusa_com_o_tipo_certo(campo):
    """`KeyError` cru tambem escaparia do despachante."""
    dados = um(IniciarCopia).para_json()
    if campo == "tipo_do_efeito":
        dados = _com_chave().para_json()
        del dados[campo]
        with pytest.raises(RegistroMalformadoError, match=campo):
            resultado_de_json(dados)
        return
    del dados[campo]
    with pytest.raises(RegistroMalformadoError, match=campo):
        efeito_de_json(dados)


def test_chave_que_nao_e_objeto_recusa():
    dados = um(IniciarCopia).para_json()
    dados["chaves_de_exclusao"] = "vda"
    with pytest.raises(RegistroMalformadoError, match="chaves_de_exclusao"):
        efeito_de_json(dados)


def test_chave_do_resultado_tambem_exige():
    """Simetria: o resultado le a chave pelo mesmo caminho do efeito."""
    dados = _com_chave().para_json()
    dados["chaves"][0]["disco"] = 42
    with pytest.raises(RegistroMalformadoError, match="disco"):
        resultado_de_json(dados)


# ── Chaves no plural: a regra passa a ser intersecao ────────────────────────


def _vm(*discos):
    return um(FecharJanela, discos=discos)


def _disco(disco):
    return um(IniciarCopia, disco=disco)


def test_efeito_de_vm_e_efeito_de_disco_com_um_disco_em_comum_se_excluem():
    """O teste que a leitura "mesma chave" reprovaria.

    Com chave no plural, "mesma" passa a ser lida como "conjuntos identicos", e
    um efeito de VM sobre tres discos conviveria com um efeito de disco sobre o
    segundo deles. Um disco em comum basta.
    """
    assert se_excluem(_vm("vda", "vdb", "vdc"), _disco("vdb"))
    assert se_excluem(_disco("vdb"), _vm("vda", "vdb", "vdc"))


def test_sem_disco_em_comum_nao_se_excluem():
    """Multi-disco copia em paralelo: exclusao e por disco, nao por VM."""
    assert not se_excluem(_vm("vda", "vdb"), _disco("vdc"))
    assert not se_excluem(_disco("vda"), _disco("vdb"))


def test_dois_efeitos_de_vm_sobre_a_mesma_vm_se_excluem():
    assert se_excluem(_vm("vda", "vdb"), _vm("vdb", "vdc"))


def test_efeitos_de_vms_diferentes_nunca_se_excluem():
    outro = um(IniciarCopia, vm_id=uuid4(), disco="vda")
    assert not se_excluem(_disco("vda"), outro)


def test_efeito_sem_disco_nao_exclui_ninguem():
    """Leitura nao bloqueia escrita, e nao e bloqueada por ela."""
    assert not se_excluem(um(InventariarVm), _vm("vda", "vdb"))
    assert not se_excluem(um(ConsultarNoDaVm), _disco("vda"))


def test_efeito_de_vm_segura_uma_chave_por_disco():
    chaves = _vm("vda", "vdb", "vdc").chaves_de_exclusao()
    assert [c.disco for c in chaves] == ["vda", "vdb", "vdc"]
    assert {c.vm_id for c in chaves} == {VM}


def test_efeito_de_vm_sem_disco_nao_existe():
    with pytest.raises(RegistroMalformadoError, match="sem disco"):
        _vm()


def test_efeito_de_vm_com_disco_repetido_nao_existe():
    """Chave repetida contaria duas vezes o mesmo disco na concessao."""
    with pytest.raises(RegistroMalformadoError, match="repetido"):
        _vm("vda", "vda")


def test_efeito_de_vm_sobrevive_a_serializacao():
    efeito = _vm("vdb", "vda", "vdc")
    assert efeito_de_json(json.loads(json.dumps(efeito.para_json()))) == efeito


def test_a_ordem_dos_discos_e_canonica():
    """Sem ordem canonica, o mesmo pedido montado duas vezes nao seria igual.

    A maquina monta a lista a partir da VM, e a reconciliacao a partir do
    inventario do hypervisor; nada garante a mesma ordem. Tres coisas quebrariam
    em silencio: desduplicar, correlacionar, e a ida e volta pelo JSON.
    """
    assert _vm("vda", "vdb") == _vm("vdb", "vda")
    assert _vm("vdc", "vda", "vdb").discos == ("vda", "vdb", "vdc")


def test_json_com_ordem_invertida_constroi_o_mesmo_valor():
    """A leitura tambem canoniza — senao o JSON vira o lado frouxo."""
    dados = _vm("vda", "vdb").para_json()
    dados["chaves_de_exclusao"].reverse()
    assert efeito_de_json(dados) == _vm("vda", "vdb")


def test_chaves_do_resultado_tambem_sao_canonicas():
    a, b = (ChaveDeExclusao(vm_id=VM, disco=d) for d in ("vda", "vdb"))
    r1 = ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="x",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(a, b),
        sucesso=True,
    )
    r2 = ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito="x",
        vm_id=VM,
        no_que_respondeu=None,
        chaves=(b, a),
        sucesso=True,
    )
    assert r1 == r2


def test_resultado_com_chave_repetida_nao_existe():
    """A construcao recusa o que a leitura ja recusava."""
    a = ChaveDeExclusao(vm_id=VM, disco="vda")
    with pytest.raises(RegistroMalformadoError, match="repetida"):
        ResultadoSimples(
            tenant_id=TENANT,
            ciclo_id=CICLO,
            tipo_do_efeito="x",
            vm_id=VM,
            no_que_respondeu=None,
            chaves=(a, a),
            sucesso=True,
        )


def test_efeito_de_disco_com_duas_chaves_recusa():
    """Um efeito de disco que chegasse com duas chaves seria contradicao entre o
    tipo e o envelope — e contradicao nao se resolve escolhendo uma."""
    dados = _disco("vda").para_json()
    dados["chaves_de_exclusao"].append({"vm_id": str(VM), "disco": "vdb"})
    with pytest.raises(RegistroMalformadoError, match="disco so"):
        efeito_de_json(dados)


def test_chaves_de_vms_diferentes_no_mesmo_efeito_recusa():
    dados = _vm("vda", "vdb").para_json()
    dados["chaves_de_exclusao"][1]["vm_id"] = str(uuid4())
    with pytest.raises(RegistroMalformadoError, match="VMs diferentes"):
        efeito_de_json(dados)


def test_chave_repetida_no_json_recusa():
    dados = _vm("vda", "vdb").para_json()
    dados["chaves_de_exclusao"][1] = dict(dados["chaves_de_exclusao"][0])
    with pytest.raises(RegistroMalformadoError, match="repetida"):
        efeito_de_json(dados)


# ── Fechar a janela e UMA unidade de execucao ───────────────────────────────


def test_fechar_janela_e_da_vm_e_nao_do_disco():
    """Checkpoint por disco daria um instante por disco — banco num, log noutro,
    ponto de recuperacao que parece valido e nao e."""
    assert issubclass(FecharJanela, EfeitoDeVm)
    assert not issubclass(FecharJanela, EfeitoDeDisco)


def test_o_efeito_antigo_de_checkpoint_por_disco_e_recusado():
    """Um agente ou uma fila numa versao anterior pode ainda ter um
    `criar_checkpoint` guardado. Ele e tipo desconhecido para esta versao, e a
    resposta e recusar — nao traduzir para `fechar_janela`, que nao e a mesma
    coisa: o antigo era por disco e nao congelava."""
    dados = _disco("vda").para_json()
    dados["tipo"] = "criar_checkpoint"
    with pytest.raises(ValorDesconhecidoError, match="tipo de efeito"):
        efeito_de_json(dados)


def test_resultado_de_efeito_de_vm_carrega_todas_as_chaves():
    """A correlacao segue a mesma tripla: ciclo, tipo e as chaves do efeito."""
    efeito = _vm("vda", "vdb")
    resultado = ResultadoSimples(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito=efeito.TIPO,
        vm_id=efeito.vm_id,
        no_que_respondeu=efeito.no,
        chaves=efeito.chaves_de_exclusao(),
        sucesso=True,
    )
    lido = resultado_de_json(json.loads(json.dumps(resultado.para_json())))
    assert lido.chaves == efeito.chaves_de_exclusao()


# ── Correlacao e igualdade; exclusao e intersecao ───────────────────────────


def _resposta(efeito):
    return ResultadoSimples(
        tenant_id=efeito.tenant_id,
        ciclo_id=efeito.ciclo_id,
        tipo_do_efeito=efeito.TIPO,
        vm_id=efeito.vm_id,
        no_que_respondeu=efeito.no,
        chaves=chaves_de(efeito),
        sucesso=True,
    )


def test_resultado_responde_ao_proprio_efeito():
    for efeito in TODOS:
        assert responde_a(_resposta(efeito), efeito), efeito.TIPO


def test_intersecao_nao_e_correlacao():
    """O erro facil: usar `se_excluem` para correlacionar, porque e a funcao que
    existe. Os dois efeitos abaixo SE EXCLUEM — um disco em comum — e o resultado
    de um NAO responde ao outro."""
    janela = _vm("vda", "vdb")
    copia = um(IniciarCopia, disco="vdb")
    assert se_excluem(janela, copia)
    assert not responde_a(_resposta(janela), copia)


def test_resposta_com_subconjunto_das_chaves_nao_responde():
    """Um efeito de VM sobre dois discos e um resultado com uma chave so."""
    janela = _vm("vda", "vdb")
    parcial = dataclasses.replace(
        _resposta(janela), chaves=(ChaveDeExclusao(vm_id=VM, disco="vda"),)
    )
    assert not responde_a(parcial, janela)


def test_resposta_com_as_chaves_em_outra_ordem_responde():
    janela = _vm("vda", "vdb")
    resposta = dataclasses.replace(_resposta(janela), chaves=tuple(reversed(chaves_de(janela))))
    assert responde_a(resposta, janela)


@pytest.mark.parametrize("campo", ["tenant_id", "ciclo_id"])
def test_resposta_de_outro_tenant_ou_ciclo_nao_responde(campo):
    """Tenant entra porque correlacao que cruzasse tenant seria o oraculo que o
    ADR-0006 fecha; ciclo, porque resultado atrasado e descartado."""
    efeito = _disco("vda")
    outra = dataclasses.replace(_resposta(efeito), **{campo: uuid4()})
    assert not responde_a(outra, efeito)


# ── As garantias do __post_init__ valem para TODA subclasse ─────────────────
#
# Em dataclass, uma subclasse que defina o proprio __post_init__ substitui o da
# base sem erro nem aviso, e a garantia desaparece. Hoje nenhuma faz isso — mas
# isso so vira propriedade se o teste percorrer o catalogo REAL de subclasses, e
# nao uma lista que alguem escreveu. Uma subclasse nova sem amostra reprova aqui.

TODOS_OS_RESULTADOS = sorted(_por_tipo(Resultado).values(), key=lambda c: c.TIPO)
TODOS_OS_EFEITOS_DE_VM = sorted(
    (c for c in _por_tipo(Efeito).values() if issubclass(c, EfeitoDeVm)), key=lambda c: c.TIPO
)
DUAS_CHAVES = (ChaveDeExclusao(vm_id=VM, disco="vda"), ChaveDeExclusao(vm_id=VM, disco="vdb"))


def _amostra(classe):
    return next(r for r in RESULTADOS if type(r) is classe)


def test_as_amostras_cobrem_todo_tipo_de_resultado():
    """Sem isto, o parametrizado abaixo cobriria so o que alguem lembrou."""
    assert {type(r) for r in RESULTADOS} == set(TODOS_OS_RESULTADOS)


@pytest.mark.parametrize("classe", TODOS_OS_RESULTADOS, ids=lambda c: c.TIPO)
def test_todo_resultado_canoniza_as_chaves(classe):
    amostra = _amostra(classe)
    a = dataclasses.replace(amostra, chaves=DUAS_CHAVES)
    b = dataclasses.replace(amostra, chaves=tuple(reversed(DUAS_CHAVES)))
    assert a == b


@pytest.mark.parametrize("classe", TODOS_OS_RESULTADOS, ids=lambda c: c.TIPO)
def test_todo_resultado_recusa_chave_repetida(classe):
    with pytest.raises(RegistroMalformadoError, match="repetida"):
        dataclasses.replace(_amostra(classe), chaves=(DUAS_CHAVES[0], DUAS_CHAVES[0]))


@pytest.mark.parametrize("classe", TODOS_OS_RESULTADOS, ids=lambda c: c.TIPO)
def test_todo_resultado_recusa_chaves_de_duas_vms(classe):
    """Zero ou uma VM. Resultado com chaves de duas nunca responderia a nada, e o
    efeito ficaria pendente para sempre esperando resposta que ja chegou."""
    outra = ChaveDeExclusao(vm_id=uuid4(), disco="vda")
    with pytest.raises(RegistroMalformadoError, match="VMs diferentes"):
        dataclasses.replace(_amostra(classe), chaves=(DUAS_CHAVES[0], outra))


@pytest.mark.parametrize("classe", TODOS_OS_EFEITOS_DE_VM, ids=lambda c: c.TIPO)
def test_todo_efeito_de_vm_canoniza_e_recusa(classe):
    assert um(classe, discos=("vdb", "vda")) == um(classe, discos=("vda", "vdb"))
    with pytest.raises(RegistroMalformadoError, match="repetido"):
        um(classe, discos=("vda", "vda"))
    with pytest.raises(RegistroMalformadoError, match="sem disco"):
        um(classe, discos=())


def test_ha_ao_menos_um_efeito_de_vm_no_catalogo():
    """Parametrizado sobre lista vazia passa sem testar nada."""
    assert TODOS_OS_EFEITOS_DE_VM


def test_resultado_de_duas_vms_no_json_tambem_recusa():
    """Os dois leitores iguais: o do efeito ja recusava; o do resultado aceitava,
    canonizava, e deixava o efeito pendente para sempre."""
    dados = _com_chave().para_json()
    dados["chaves"].append({"vm_id": str(uuid4()), "disco": "vdb"})
    with pytest.raises(RegistroMalformadoError, match="VMs diferentes"):
        resultado_de_json(dados)


@pytest.mark.parametrize("classe", TODOS_OS_RESULTADOS, ids=lambda c: c.TIPO)
def test_todo_resultado_aceita_ficar_sem_chave(classe):
    """Zero VM e legitimo — efeito sem chave tem resultado sem chave.

    Afirma a propriedade sobre todo tipo de resultado, e nao sobre o elemento que
    por acaso estava numa posicao da lista. A versao anterior dizia
    `RESULTADOS[3].chaves == ()`: reordenar a lista quebrava o teste sem quebrar
    nada, e trocar o elemento deixava como conserto "escolhe outro indice".
    """
    assert dataclasses.replace(_amostra(classe), chaves=()).chaves == ()


# ── Todo efeito tem sujeito; o de agente diz o no ───────────────────────────

TODOS_OS_EFEITOS = sorted(_por_tipo(Efeito).values(), key=lambda c: c.TIPO)
DE_AGENTE = [c for c in TODOS_OS_EFEITOS if c.ALVO is Alvo.AGENTE_DE_ORIGEM]
SEM_AGENTE = [c for c in TODOS_OS_EFEITOS if c.ALVO is not Alvo.AGENTE_DE_ORIGEM]


def _variantes(efeito):
    """Efeitos DIFERENTES do mesmo tipo, tenant e ciclo — um por eixo de identidade."""
    yield "outra VM", dataclasses.replace(efeito, vm_id=uuid4())
    if efeito.no is not None:
        yield "outro no", dataclasses.replace(efeito, no="no-99")
    if isinstance(efeito, EfeitoDeDisco):
        yield "outro disco", dataclasses.replace(efeito, disco="vdz")
    if isinstance(efeito, EfeitoDeVm):
        yield "outros discos", dataclasses.replace(efeito, discos=("vdx", "vdy"))


@pytest.mark.parametrize("classe", TODOS_OS_EFEITOS, ids=lambda c: c.TIPO)
def test_nenhum_resultado_responde_a_outro_efeito_do_mesmo_tipo(classe):
    """A propriedade que teria pegado a classe sem chave na T3, e que passa a pegar
    o proximo efeito que alguem acrescentar sem sujeito.

    Percorre o catalogo REAL. Para cada tipo, o resultado de um efeito responde a
    ele e a nenhum outro do mesmo tipo, tenant e ciclo — mude a VM, o no, o disco.
    """
    efeito = um(classe)
    assert responde_a(_resposta(efeito), efeito)
    for eixo, outro in _variantes(efeito):
        assert not responde_a(_resposta(efeito), outro), eixo


def test_o_catalogo_de_efeitos_nao_esta_vazio():
    assert TODOS_OS_EFEITOS and DE_AGENTE and SEM_AGENTE


@pytest.mark.parametrize("classe", DE_AGENTE, ids=lambda c: c.TIPO)
def test_efeito_de_agente_sem_no_nao_existe(classe):
    """Agentes de nos diferentes falham separado: sem o no, "agente de origem"
    nao e um alvo, sao varios."""
    with pytest.raises(RegistroMalformadoError, match="em qual no"):
        um(classe, no=None)


@pytest.mark.parametrize("classe", SEM_AGENTE, ids=lambda c: c.TIPO)
def test_efeito_que_nao_roda_em_agente_nao_leva_no(classe):
    with pytest.raises(RegistroMalformadoError, match="nao leva no"):
        um(classe, no="no-01")


@pytest.mark.parametrize("no", ["", " no-01", "no 01", "no/01", "-no"])
def test_no_malformado_recusa(no):
    with pytest.raises(RegistroMalformadoError):
        um(IniciarCopia, no=no)


@pytest.mark.parametrize("classe", TODOS_OS_EFEITOS, ids=lambda c: c.TIPO)
def test_sujeito_e_no_sobrevivem_a_serializacao(classe):
    efeito = um(classe)
    lido = efeito_de_json(json.loads(json.dumps(efeito.para_json())))
    assert (lido.vm_id, lido.no) == (efeito.vm_id, efeito.no)


def test_chaves_de_outra_vm_que_nao_o_sujeito_recusa():
    """Duas expressoes da VM no mesmo efeito tem que concordar — senao a fila
    exclui por uma VM e o agente age sobre outra."""
    dados = _disco("vda").para_json()
    dados["vm_id"] = str(uuid4())
    with pytest.raises(RegistroMalformadoError, match="diferentes do sujeito"):
        efeito_de_json(dados)


# ── Leitura nao segura chave ────────────────────────────────────────────────


@pytest.mark.parametrize("classe", [InventariarVm, ConsultarNoDaVm], ids=lambda c: c.TIPO)
def test_leitura_nao_segura_chave_e_nao_espera_o_zumbi(classe):
    """O vm_id da leitura NAO e chave, e isto e deliberado.

    Com chave, a consulta de evidencia so rodaria com o lease livre — e o lease
    esta preso pela copia zumbi que e a razao de ela existir. Deadlock, e nao se
    resolve com preempcao: uma leitura nao retira nada de ninguem.
    """
    leitura = um(classe)
    copia_zumbi = um(IniciarCopia, disco="vda")
    assert chaves_de(leitura) == ()
    assert not se_excluem(leitura, copia_zumbi)


# ── "A VM nao esta aqui" e desfecho proprio ─────────────────────────────────


def test_vm_ausente_responde_e_nao_e_inventario_vazio():
    """A VM migrou entre a indicacao do Nova e a execucao. O no respondeu e o
    indicado — a conferencia de no passa. Um inventario vazio seria verdade sobre
    o no e mentira sobre a VM; a resposta e outra coisa, de outro tipo."""
    inventario = um(InventariarVm)
    ausente = ResultadoVmAusente(
        tenant_id=TENANT,
        ciclo_id=CICLO,
        tipo_do_efeito=inventario.TIPO,
        vm_id=inventario.vm_id,
        no_que_respondeu=inventario.no,
        chaves=(),
    )
    assert responde_a(ausente, inventario)
    assert not isinstance(ausente, ResultadoDeInventario)


@pytest.mark.parametrize("classe", DE_AGENTE, ids=lambda c: c.TIPO)
def test_todo_efeito_de_agente_pode_ouvir_vm_ausente(classe):
    """Qualquer efeito de agente pode chegar a um no de onde a VM ja saiu."""
    efeito = um(classe)
    ausente = ResultadoVmAusente(
        tenant_id=efeito.tenant_id,
        ciclo_id=efeito.ciclo_id,
        tipo_do_efeito=efeito.TIPO,
        vm_id=efeito.vm_id,
        no_que_respondeu=efeito.no,
        chaves=chaves_de(efeito),
    )
    assert responde_a(ausente, efeito)


def test_resposta_de_outro_no_nao_responde():
    """O agente de outro no nao responde por este."""
    inventario = um(InventariarVm)
    de_outro_no = dataclasses.replace(_resposta(inventario), no_que_respondeu="no-02")
    assert not responde_a(de_outro_no, inventario)
