"""A maquina do ciclo: o caminho normal, e o desfecho de quem para no meio.

Os primeiros testes sao sobre o DESFECHO, e nao sobre transicao: e ali que o mesmo
conceito nasceria duas vezes — o erro que a `degradada` ja custou entre a dr-006 e
a dr-001.
"""

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, get_type_hints
from uuid import uuid4

import pytest

from vzdr.core.domain import ciclo
from vzdr.core.domain.ciclo import (
    ETAPAS_DA_FASE,
    RESULTADO_ESPERADO,
    EstadoDoCiclo,
    Fase,
    MigracaoSemResyncError,
    Transicao,
    TransicaoInvalidaError,
    abandonar,
    avancar,
    iniciar,
    no_do_proximo_ciclo,
)
from vzdr.core.domain.efeitos import (
    Alvo,
    ConsultarNoDaVm,
    DiscoNoInventario,
    Efeito,
    EstadoDoBitmap,
    FecharJanela,
    ImagemNoInventario,
    IniciarCopia,
    RegistrarPontoDeRecuperacao,
    Resultado,
    ResultadoDeCopia,
    ResultadoDeInventario,
    ResultadoDeLocalizacao,
    ResultadoSimples,
    ResultadoVmAusente,
    _por_tipo,
    chaves_de,
)
from vzdr.core.domain.saude import Desfecho, taxa_de_falha

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
UM_MINUTO = timedelta(minutes=1)
TENANT = uuid4()
CICLO = uuid4()
VM = uuid4()
DISCOS = ("vda", "vdb")
NO = "no-1"
CAMINHO_NORMAL = [f for f in Fase if f is not Fase.CERCANDO]


#: Um disco gravavel por disco do ciclo, com um bitmap como a M5 o mediu.
INVENTARIO_BOM = tuple(
    DiscoNoInventario(
        disco=d,
        somente_leitura=False,
        cadeia=(
            ImagemNoInventario(
                bitmaps=(
                    EstadoDoBitmap(
                        nome="vzdr-ckp-" + "a" * 32,
                        granularity=65536,
                        count=0,
                        recording=True,
                        busy=False,
                        persistent=True,
                        inconsistent=False,
                    ),
                )
            ),
        ),
    )
    for d in DISCOS
)


# ── Como se responde ────────────────────────────────────────────────────────


def _base(efeito: Efeito, ciclo_id=None) -> dict:
    """Responde ao proprio efeito — ou, com `ciclo_id`, finge vir de outro ciclo."""
    return {
        "tenant_id": efeito.tenant_id,
        "ciclo_id": ciclo_id or efeito.ciclo_id,
        "tipo_do_efeito": efeito.TIPO,
        "chaves": chaves_de(efeito),
        "vm_id": efeito.vm_id,
        "no_que_respondeu": efeito.no,
    }


def sucesso(efeito: Efeito, ciclo_id=None) -> Resultado:
    classe = RESULTADO_ESPERADO[type(efeito)]
    corpo = {
        ResultadoSimples: {"sucesso": True},
        ResultadoDeCopia: {"bytes_transferidos": 1, "concluido": True},
        ResultadoDeInventario: {"discos": INVENTARIO_BOM, "checkpoints": (), "jobs_em_curso": ()},
        ResultadoDeLocalizacao: {"no_atual": NO},
    }[classe]
    return classe(**_base(efeito, ciclo_id), **corpo)


def fracasso(efeito: Efeito) -> Resultado:
    """O "nao deu" de cada tipo de resultado. Na localizacao, e a VM em outro no."""
    classe = RESULTADO_ESPERADO[type(efeito)]
    corpo = {
        ResultadoSimples: {"sucesso": False, "motivo": "teste"},
        ResultadoDeCopia: {"bytes_transferidos": 0, "concluido": False},
        ResultadoDeInventario: {
            "discos": INVENTARIO_BOM,
            "checkpoints": (),
            "jobs_em_curso": ("backup-vda-libvirt-1-format",),
        },
        ResultadoDeLocalizacao: {"no_atual": "no-2"},
    }[classe]
    return classe(**_base(efeito), **corpo)


def comecar() -> Transicao:
    return iniciar(TENANT, CICLO, VM, DISCOS, NO, T0)


def responder_tudo(transicao: Transicao, agora: datetime) -> Transicao:
    """Responde com sucesso, um a um, todos os pendentes."""
    for efeito in transicao.estado.pendentes:
        transicao = avancar(transicao.estado, sucesso(efeito), agora)
    return transicao


def ate(fase: Fase) -> Transicao:
    """O ciclo no comeco de `fase`, pelo caminho normal, um minuto por fase."""
    transicao, agora = comecar(), T0
    while transicao.estado.fase is not fase:
        agora += UM_MINUTO
        transicao = responder_tudo(transicao, agora)
        assert not transicao.terminou, transicao.estado
    return transicao


def ate_o_fim() -> list[Transicao]:
    transicoes, agora = [comecar()], T0
    while not transicoes[-1].terminou:
        agora += UM_MINUTO
        transicoes.append(responder_tudo(transicoes[-1], agora))
    return transicoes


def abandonar_em(fase: Fase) -> Transicao:
    estado = ate(fase).estado
    return avancar(estado, fracasso(estado.pendentes[0]), T0 + timedelta(hours=1))


# ── O desfecho: um conceito, em um lugar ────────────────────────────────────


def test_o_desfecho_do_ciclo_e_o_de_saude():
    """Nos dois sentidos, por estrutura.

    Do ciclo para a saude: o campo e tipado `saude.Desfecho`, e o modulo nao define
    enum nenhum alem de `Fase` — um desfecho novo em ciclo.py nao tem onde ser
    escrito. Da saude para o ciclo: `test_todo_desfecho_e_alcancavel`, logo abaixo.
    """
    assert get_type_hints(EstadoDoCiclo)["desfecho"] == Optional[Desfecho]
    arvore = ast.parse(Path(ciclo.__file__).read_text(encoding="utf-8"))
    enums = [
        no.name
        for no in ast.walk(arvore)
        if isinstance(no, ast.ClassDef)
        and any(isinstance(b, ast.Attribute) and b.attr.endswith("Enum") for b in no.bases)
    ]
    assert enums == ["Fase"], enums


#: Como chegar a cada desfecho. Indexado PELO enum: desfecho novo em saude.py e
#: KeyError aqui, e a maquina tem que saber produzi-lo antes de o teste passar.
COMO_ALCANCAR = {
    Desfecho.CONCLUIDO: lambda: ate_o_fim()[-1],
    Desfecho.FALHOU: lambda: abandonar_em(Fase.COPIANDO),
    Desfecho.NUNCA_INICIOU: lambda: abandonar_em(Fase.VALIDANDO),
}


@pytest.mark.parametrize("desfecho", list(Desfecho), ids=lambda d: d.value)
def test_todo_desfecho_e_alcancavel(desfecho):
    """Valor de saude.Desfecho que a maquina nunca produz e conceito morto — ou
    um conceito que a maquina deveria produzir e esqueceu."""
    transicao = COMO_ALCANCAR[desfecho]()
    assert transicao.terminou
    assert transicao.estado.desfecho is desfecho


def test_nunca_iniciou_fica_fora_da_taxa_e_nao_produz_ponto():
    """Exercita a regra de saude.py com o que a maquina produz, sem redize-la.

    Fora da taxa e conta de `taxa_de_falha`; aqui so se confere que o ciclo que
    nunca iniciou chega la como o desfecho que ela exclui — e que ele nao produziu
    ponto, que e o que faz a idade continuar crescendo.
    """
    estado = abandonar_em(Fase.VALIDANDO).estado
    assert taxa_de_falha([estado.desfecho]) is None
    assert estado.ponto_registrado_em is None


@pytest.mark.parametrize("fase", [Fase.LOCALIZANDO, Fase.VALIDANDO], ids=lambda f: f.value)
def test_o_desfecho_sai_do_residuo_e_nao_da_fase(fase):
    """A reentrada da T7: VM que migra no meio e localizada de novo. Numa fase de
    leitura, com um checkpoint ja criado, o abandono e FALHOU — e nao "nunca
    iniciou", que tiraria trabalho tentado da taxa de falha."""
    estado = replace(ate(fase).estado, ja_deixou_residuo=True)
    assert abandonar(estado, T0).estado.desfecho is Desfecho.FALHOU


def test_falha_depois_do_ponto_e_concluido():
    """LIBERANDO: o ponto existe. Falhar ali deixa residuo, e nao desfaz protecao."""
    estado = abandonar_em(Fase.LIBERANDO).estado
    assert estado.desfecho is Desfecho.CONCLUIDO
    assert estado.ponto_registrado_em is not None


# ── ja_deixou_residuo: so vira verdadeiro ──────────────────────────────────


def _entradas(estado: EstadoDoCiclo) -> dict[str, Optional[Resultado]]:
    efeito = estado.pendentes[0]
    entradas: dict[str, Optional[Resultado]] = {
        "nada": None,
        "sucesso": sucesso(efeito),
        "fracasso": fracasso(efeito),
        "de_outro_ciclo": sucesso(efeito, ciclo_id=uuid4()),
    }
    if efeito.ALVO is Alvo.AGENTE_DE_ORIGEM:
        entradas["vm_ausente"] = ResultadoVmAusente(**_base(efeito))
    return entradas


def _de_agente(fase: Fase) -> bool:
    return ETAPAS_DA_FASE[fase][0][0].ALVO is Alvo.AGENTE_DE_ORIGEM


#: Toda fase do caminho normal, com toda entrada que pode chegar a ela. "A VM nao
#: esta aqui" so chega a efeito de agente — derivado da tabela, e nao pulado.
TRANSICOES = [
    (fase, tipo)
    for fase in CAMINHO_NORMAL
    for tipo in ["nada", "sucesso", "fracasso", "de_outro_ciclo"]
    + (["vm_ausente"] if _de_agente(fase) else [])
]


@pytest.mark.parametrize(("fase", "tipo"), TRANSICOES, ids=lambda x: getattr(x, "value", x))
@pytest.mark.parametrize("residuo_antes", [False, True])
def test_nenhuma_transicao_devolve_o_residuo_a_falso(fase, tipo, residuo_antes):
    """Sobre toda fase do caminho normal e toda forma de entrada — inclusive com o
    residuo ja verdadeiro numa leitura, que e o estado da reentrada."""
    estado = ate(fase).estado
    estado = replace(estado, ja_deixou_residuo=estado.ja_deixou_residuo or residuo_antes)
    depois = avancar(estado, _entradas(estado)[tipo], T0 + timedelta(hours=1)).estado
    assert depois.ja_deixou_residuo or not estado.ja_deixou_residuo


# ── O caminho normal ────────────────────────────────────────────────────────


def test_o_caminho_normal_percorre_as_fases_em_ordem_e_conclui():
    transicoes = ate_o_fim()
    fases = []
    for t in transicoes[:-1]:
        if not fases or fases[-1] is not t.estado.fase:
            fases.append(t.estado.fase)
    assert fases == CAMINHO_NORMAL
    assert transicoes[-1].estado.desfecho is Desfecho.CONCLUIDO
    assert transicoes[-1].efeitos == ()


def test_a_primeira_coisa_e_perguntar_ao_nova_onde_a_vm_esta():
    """ADR-0012: o no e comparado antes de qualquer coisa. Nenhum efeito de agente
    e pedido antes de o Nova responder."""
    primeira = comecar()
    assert [type(e) for e in primeira.efeitos] == [ConsultarNoDaVm]
    assert all(e.ALVO is not Alvo.AGENTE_DE_ORIGEM for e in primeira.efeitos)


def test_migracao_detectada_o_ciclo_nao_executa():
    """No atual diferente do gravado: o bitmap atravessou evento de host e nao e
    usado. O ciclo termina sem pedir nada e diz por que. Quem criaria o resync nao
    existe ainda (M4); o que impede o proximo ciclo de errar e
    `no_do_proximo_ciclo`, testado abaixo."""
    t = comecar()
    t = avancar(t.estado, fracasso(t.estado.pendentes[0]), T0 + UM_MINUTO)
    assert t.estado.migracao_detectada
    assert t.estado.desfecho is Desfecho.NUNCA_INICIOU
    assert t.efeitos == ()


def test_todo_efeito_pedido_e_deste_ciclo_desta_vm_e_do_no_gravado():
    for t in ate_o_fim():
        for efeito in t.efeitos:
            assert (efeito.tenant_id, efeito.ciclo_id, efeito.vm_id) == (TENANT, CICLO, VM)
            esperado = NO if efeito.ALVO is Alvo.AGENTE_DE_ORIGEM else None
            assert efeito.no == esperado, efeito


def test_cada_etapa_e_pedida_so_depois_da_anterior_responder_inteira():
    """LIBERANDO e ordenada: com um disco ainda pendente, nada da etapa seguinte."""
    t = ate(Fase.LIBERANDO)
    for etapa in ETAPAS_DA_FASE[Fase.LIBERANDO]:
        assert {type(e) for e in t.efeitos} == set(etapa)
        primeiro, *resto = t.estado.pendentes
        t = avancar(t.estado, sucesso(primeiro), T0)
        if resto:
            assert t.efeitos == (), "etapa seguinte pedida com a anterior pendente"
            t = responder_tudo(t, T0)
    assert t.estado.desfecho is Desfecho.CONCLUIDO


def test_o_ponto_e_registrado_no_instante_da_resposta():
    t = ate(Fase.REGISTRANDO_PONTO)
    (registrar,) = t.estado.pendentes
    assert isinstance(registrar, RegistrarPontoDeRecuperacao)
    quando = T0 + timedelta(hours=3)
    assert avancar(t.estado, sucesso(registrar), quando).estado.ponto_registrado_em == quando


def test_fase_desde_so_muda_ao_entrar_numa_fase():
    """Um disco respondendo nao e fase nova; o ultimo, e. O tempo passar, nunca."""
    t = ate(Fase.COPIANDO)
    entrou = t.estado.fase_desde
    vda, vdb = t.estado.pendentes
    t = avancar(t.estado, sucesso(vda), entrou + UM_MINUTO)
    assert t.estado.fase_desde == entrou
    t = avancar(t.estado, None, entrou + timedelta(hours=5))
    assert t.estado.fase_desde == entrou
    t = avancar(t.estado, sucesso(vdb), entrou + timedelta(hours=6))
    assert t.estado.fase is Fase.CONFIRMANDO
    assert t.estado.fase_desde == entrou + timedelta(hours=6)
    assert t.estado.iniciado_em == T0


# ── O que nao muda nada, e o que e recusado ─────────────────────────────────


def test_entrada_none_e_nada_aconteceu_e_nao_terminou():
    """Um tipo de retorno: mesmo estado, zero efeitos. E zero efeitos NAO e
    "terminou" — isso e campo."""
    estado = ate(Fase.COPIANDO).estado
    t = avancar(estado, None, T0 + timedelta(days=3))
    assert t.estado == estado
    assert t.efeitos == ()
    assert not t.terminou


def test_resultado_de_outro_ciclo_e_descartado():
    estado = ate(Fase.COPIANDO).estado
    t = avancar(estado, sucesso(estado.pendentes[0], ciclo_id=uuid4()), T0)
    assert (t.estado, t.efeitos) == (estado, ())


def test_resultado_repetido_nao_conta_duas_vezes():
    estado = ate(Fase.COPIANDO).estado
    resposta = sucesso(estado.pendentes[0])
    uma = avancar(estado, resposta, T0)
    duas = avancar(uma.estado, resposta, T0)
    assert (duas.estado, duas.efeitos) == (uma.estado, ())
    assert len(uma.estado.pendentes) == len(estado.pendentes) - 1


def test_ciclo_terminado_descarta_tudo():
    fim = ate_o_fim()[-1].estado
    atrasado = sucesso(ate(Fase.COPIANDO).estado.pendentes[0])
    for entrada in (None, atrasado):
        t = avancar(fim, entrada, T0 + timedelta(days=1))
        assert (t.estado, t.efeitos) == (fim, ())


def test_terminado_descarta_ate_resposta_a_efeito_que_ficou_pendente():
    """A condicao que o teste acima nao cria: ciclo terminado COM pendentes. Hoje
    terminar esvazia os pendentes, e a guarda e redundante com isso — o arnes a
    tirou e nada reprovou. Na T6 o abandono pede limpeza, e o ciclo termina com
    efeitos no ar; a resposta deles e evidencia para a reconciliacao (T7), e nao
    reabre o ciclo. Caminho que nunca executa onde se testa precisa de teste que
    o force."""
    em_copia = ate(Fase.COPIANDO).estado
    pendente = em_copia.pendentes[0]
    terminado = replace(em_copia, desfecho=Desfecho.FALHOU)
    t = avancar(terminado, sucesso(pendente), T0 + timedelta(days=1))
    assert (t.estado, t.efeitos) == (terminado, ())


def test_resultado_do_tipo_errado_e_recusado():
    """Responde a um pendente, e nao e o tipo que o responde: contrato quebrado."""
    estado = ate(Fase.FECHANDO_JANELA).estado
    (fechar,) = estado.pendentes
    errado = ResultadoDeCopia(**_base(fechar), bytes_transferidos=1, concluido=True)
    with pytest.raises(TransicaoInvalidaError, match="fechar_janela"):
        avancar(estado, errado, T0)


def test_instante_sem_fuso_e_recusado():
    estado = ate(Fase.COPIANDO).estado
    with pytest.raises(ValueError, match="sem fuso"):
        avancar(estado, None, datetime(2026, 10, 1, 12, 0))
    with pytest.raises(ValueError, match="sem fuso"):
        iniciar(TENANT, CICLO, VM, DISCOS, NO, datetime(2026, 10, 1, 12, 0))


def test_todo_efeito_do_catalogo_tem_resultado_esperado():
    """Efeito novo sem entrada aqui seria KeyError so quando alguem o respondesse."""
    assert set(RESULTADO_ESPERADO) == set(_por_tipo(Efeito).values())


def test_copia_que_responde_sem_concluir_nao_concluiu():
    """Resultado e resposta final, e nao relatorio de progresso."""
    estado = ate(Fase.COPIANDO).estado
    copia = estado.pendentes[0]
    assert isinstance(copia, IniciarCopia)
    assert avancar(estado, fracasso(copia), T0).estado.desfecho is Desfecho.FALHOU


# ── O no do proximo ciclo ───────────────────────────────────────────────────


def _migrado() -> EstadoDoCiclo:
    t = comecar()
    return avancar(t.estado, fracasso(t.estado.pendentes[0]), T0 + UM_MINUTO).estado


def test_depois_de_migracao_os_dois_nos_candidatos_estao_errados():
    """Por que `no_do_proximo_ciclo` recusa, em vez de escolher um.

    Com o no gravado, o proximo ciclo detecta a migracao de novo — laco silencioso
    de NUNCA_INICIOU, fora da taxa de falha. Com o encontrado, nao detecta nada e
    segue para escrever com o bitmap que atravessou o evento de host."""
    migrado = _migrado()
    gravado = iniciar(TENANT, uuid4(), VM, DISCOS, migrado.no_de_origem, T0)
    gravado = avancar(gravado.estado, fracasso(gravado.estado.pendentes[0]), T0)
    assert gravado.estado.migracao_detectada, "com o no gravado: detecta de novo"

    encontrado = iniciar(TENANT, uuid4(), VM, DISCOS, migrado.no_encontrado, T0)
    consulta = encontrado.estado.pendentes[0]
    resposta = ResultadoDeLocalizacao(**_base(consulta), no_atual="no-2")
    encontrado = avancar(encontrado.estado, resposta, T0)
    assert not encontrado.estado.migracao_detectada, "com o encontrado: nao detecta nada"
    assert encontrado.estado.fase is Fase.VALIDANDO


def test_no_do_proximo_ciclo_recusa_depois_de_migracao():
    with pytest.raises(MigracaoSemResyncError, match="ressincronizada"):
        no_do_proximo_ciclo(_migrado())


def test_no_do_proximo_ciclo_sem_migracao():
    assert no_do_proximo_ciclo(ate_o_fim()[-1].estado) == NO
    # O Nova nao chegou a responder: fica o gravado.
    sem_resposta = abandonar(comecar().estado, T0).estado
    assert sem_resposta.no_encontrado is None
    assert no_do_proximo_ciclo(sem_resposta) == NO


def test_no_do_proximo_ciclo_de_ciclo_que_ainda_corre_e_erro():
    with pytest.raises(ValueError, match="ainda corre"):
        no_do_proximo_ciclo(ate(Fase.COPIANDO).estado)


# ── O que a maquina guarda, e de onde ───────────────────────────────────────


@pytest.mark.parametrize("jobs", [(), ("backup-vda-libvirt-1-format",)], ids=["sem_job", "com_job"])
def test_o_inventario_fica_no_estado(jobs):
    """Com job ou sem, a evidencia nao morre dentro de `avancar`."""
    estado = ate(Fase.VALIDANDO).estado
    (inventario,) = estado.pendentes
    resposta = ResultadoDeInventario(
        **_base(inventario),
        discos=INVENTARIO_BOM,
        checkpoints=("vzdr-ckp-" + "a" * 32,),
        jobs_em_curso=jobs,
    )
    assert avancar(estado, resposta, T0).estado.inventario == resposta


def test_efeito_de_agente_leva_o_no_que_o_nova_disse_e_nao_o_gravado():
    """Procedencia (ADR-0015): o no do efeito e o da ultima consulta ao Nova. Os
    dois so diferem aqui porque o estado e montado a mao — e e para isso."""
    estado = replace(ate(Fase.VALIDANDO).estado, no_encontrado="no-9")
    (inventario,) = estado.pendentes
    t = avancar(estado, sucesso(inventario), T0)
    (fechar,) = t.efeitos
    assert isinstance(fechar, FecharJanela)
    assert fechar.no == "no-9"


def test_efeito_respondido_sai_mesmo_que_o_estado_canonize_os_pendentes(monkeypatch):
    """Por valor, e nao por identidade — no caminho em que identidade quebra.

    O respondido e achado em `estado.pendentes`, e filtrado de um estado que ja
    passou por `replace` (no inventario, para guardar os nomes). Hoje o
    `__post_init__` nao toca os pendentes, e a tupla atravessa por referencia: a
    identidade sobrevive. No dia em que alguem os canonizar ali — e este
    repositorio canoniza tudo —, ela quebra, o respondido nunca sai, e o ciclo
    espera para sempre. O monkeypatch e esse dia. Uma versao anterior deste teste
    reconstruia a tupla ANTES da busca, e o arnes mostrou que ela nao forcava nada.
    """
    original = EstadoDoCiclo.__post_init__

    def canonizando(self):
        original(self)
        object.__setattr__(self, "pendentes", tuple(replace(e) for e in self.pendentes))

    estado = ate(Fase.VALIDANDO).estado
    (inventario,) = estado.pendentes
    monkeypatch.setattr(EstadoDoCiclo, "__post_init__", canonizando)
    t = avancar(estado, sucesso(inventario), T0)
    assert t.estado.fase is Fase.FECHANDO_JANELA, t.estado.pendentes


def test_fase_fora_do_caminho_normal_e_recusada_com_o_erro_do_contrato():
    """CERCANDO e da T7. Ate la, chegar nela e contrato quebrado, e o diagnostico
    e o do contrato — nao um traceback de `list.index`."""
    estado = ate(Fase.COPIANDO).estado
    cercando = replace(estado, fase=Fase.CERCANDO)
    with pytest.raises(TransicaoInvalidaError, match="T7"):
        avancar(cercando, sucesso(estado.pendentes[0]), T0)
