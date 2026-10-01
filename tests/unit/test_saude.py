"""Saude da protecao: conta sobre fatos, com o relogio vindo de fora."""

import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import vzdr.core.domain as dominio
from vzdr.core.domain.saude import (
    FATOR_PADRAO,
    Desfecho,
    esta_degradada,
    idade_do_ponto,
    taxa_de_falha,
)

HORA = timedelta(hours=1)
DIA = timedelta(hours=24)
UM_SEGUNDO = timedelta(seconds=1)
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


# ── degradada: por tempo, em multiplos do RPO ───────────────────────────────


def test_um_rpo_nao_degrada():
    """Um ciclo perdido e ruido."""
    assert not esta_degradada(HORA, rpo=HORA)


def test_exatamente_dois_rpo_ainda_nao_degrada():
    """Estritamente maior. O teste e preciso sobre onde a fronteira mora."""
    assert not esta_degradada(2 * HORA, rpo=HORA)


def test_passou_de_dois_rpo_degrada():
    """Dois ciclos perdidos e padrao."""
    assert esta_degradada(2 * HORA + UM_SEGUNDO, rpo=HORA)


def test_por_tempo_e_nao_por_tentativas():
    """Tres horas sem ponto degradam um tier de 1 hora e nao um de 24.

    Contar tentativas trataria as duas situacoes igual — tres falhas sao tres
    falhas —, e elas sao diferentes: uma perdeu tres pontos prometidos, a outra
    nao perdeu nenhum.
    """
    tres_horas = 3 * HORA
    assert esta_degradada(tres_horas, rpo=HORA)
    assert not esta_degradada(tres_horas, rpo=DIA)


@pytest.mark.parametrize("rpo", [HORA, DIA, timedelta(minutes=15)])
def test_a_mesma_conta_serve_qualquer_tier(rpo):
    assert not esta_degradada(2 * rpo, rpo=rpo)
    assert esta_degradada(2 * rpo + UM_SEGUNDO, rpo=rpo)


def test_o_padrao_e_dois_rpo():
    assert FATOR_PADRAO == 2.0
    assert esta_degradada(2 * HORA + UM_SEGUNDO, rpo=HORA) == esta_degradada(
        2 * HORA + UM_SEGUNDO, rpo=HORA, fator=FATOR_PADRAO
    )


def test_o_fator_e_parametro_e_muda_a_fronteira():
    """Depende de perfil de parque, e a spec proibe constante derivada de parque."""
    idade = 2 * HORA + UM_SEGUNDO
    assert esta_degradada(idade, rpo=HORA, fator=2.0)
    assert not esta_degradada(idade, rpo=HORA, fator=3.0)


@pytest.mark.parametrize("rpo", [timedelta(0), -HORA])
def test_rpo_que_nao_e_positivo_recusa(rpo):
    """RPO zero tornaria toda VM degradada o tempo todo, em silencio."""
    with pytest.raises(ValueError, match="RPO"):
        esta_degradada(HORA, rpo=rpo)


@pytest.mark.parametrize("fator", [0, -1.0])
def test_fator_que_nao_e_positivo_recusa(fator):
    with pytest.raises(ValueError, match="fator"):
        esta_degradada(HORA, rpo=HORA, fator=fator)


# ── idade do ponto: o relogio vem de fora ───────────────────────────────────


def test_a_idade_usa_o_agora_que_recebe():
    """Instante fixo, resultado fixo. E o que o `now()` por dentro tornaria
    impossivel de testar."""
    assert idade_do_ponto(T0, agora=T0 + 3 * HORA) == 3 * HORA


def test_sem_ponto_nao_e_idade_zero_nem_infinita():
    """VM sem ponto ainda nao esta protegida, que e outra coisa que degradada.

    Idade zero diria "em dia" de uma VM que ainda esta no seed; idade infinita
    diria "degradada" de uma que nunca foi protegida. Os dois estados sao
    diferentes, e quem chama decide o que mostrar.
    """
    assert idade_do_ponto(None, agora=T0) is None


def test_misturar_hora_com_e_sem_fuso_levanta():
    """Subtrair hora local de UTC daria idade errada por horas, em silencio.

    O proprio Python recusa, e o teste fixa que ninguem "conserta" isso
    removendo o fuso de um dos lados.
    """
    sem_fuso = datetime(2026, 9, 29, 12, 0)
    with pytest.raises(TypeError):
        idade_do_ponto(sem_fuso, agora=T0)


# ── taxa de falha: o que nao aconteceu nao conta ────────────────────────────


def test_nunca_iniciou_fica_fora_do_numerador_e_do_denominador():
    """Fora so do numerador, ele DILUIRIA a taxa, e ciclo que nao aconteceu
    faria a confiabilidade parecer melhor do que e."""
    desfechos = [Desfecho.CONCLUIDO, Desfecho.FALHOU] + [Desfecho.NUNCA_INICIOU] * 8
    assert taxa_de_falha(desfechos) == 0.5


def test_sem_tentativa_a_taxa_e_desconhecida_e_nao_zero():
    """Zero sobre zero como zero diria "confiabilidade perfeita" sem evidencia."""
    assert taxa_de_falha([]) is None


def test_so_nunca_iniciou_tambem_e_desconhecida():
    """O caso em que "0% de falha" seria mais falso: nada rodou."""
    assert taxa_de_falha([Desfecho.NUNCA_INICIOU] * 5) is None


def test_taxa_de_falha_aceita_qualquer_iteravel():
    """Consulta ao banco devolve cursor, nao lista."""
    assert taxa_de_falha(d for d in [Desfecho.FALHOU, Desfecho.CONCLUIDO]) == 0.5


def test_nunca_iniciou_degrada_mas_nao_e_falha():
    """As duas metricas no mesmo cenario, e o mesmo desfecho contando numa so.

    Ultimo ponto em T0; depois disso, tres ciclos que nunca iniciaram. Nenhum
    produziu ponto, entao a idade seguiu crescendo e a VM degradou. Mas nenhum
    deles foi tentativa, entao a taxa de falha nao tem o que dizer.
    """
    depois = [Desfecho.NUNCA_INICIOU] * 3
    idade = idade_do_ponto(T0, agora=T0 + 3 * HORA)
    assert idade is not None
    assert esta_degradada(idade, rpo=HORA)
    assert taxa_de_falha(depois) is None


# ── Verificado, nao combinado ───────────────────────────────────────────────

#: Atributos que leem o relogio. `time` entra mesmo sabendo que `datetime.time()`
#: nao le hora nenhuma: este modulo nao precisa de nenhum dos dois, e uma lista
#: estrita que da falso positivo e melhor que uma frouxa que deixa passar.
LEEM_O_RELOGIO = {
    "now",
    "utcnow",
    "today",
    "time",
    "time_ns",
    "monotonic",
    "monotonic_ns",
    "perf_counter",
    "perf_counter_ns",
    "localtime",
    "gmtime",
}


def _leituras_de_relogio(arvore: ast.AST) -> list[str]:
    achadas = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            achadas += [f"import {a.name}" for a in no.names if a.name.split(".")[0] == "time"]
        elif isinstance(no, ast.ImportFrom) and (no.module or "").split(".")[0] == "time":
            achadas.append(f"from {no.module} import ...")
        elif isinstance(no, ast.Attribute) and no.attr in LEEM_O_RELOGIO:
            achadas.append(f".{no.attr} na linha {no.lineno}")
        elif isinstance(no, ast.ImportFrom) and no.module == "datetime":
            # `from datetime import datetime` e legitimo; o que pega e a chamada
            # depois, pelo atributo. Mas importar um nome de relogio direto nao.
            achadas += [
                f"from datetime import {a.name}" for a in no.names if a.name in LEEM_O_RELOGIO
            ]
    return achadas


MODULOS_DO_DOMINIO = sorted(Path(dominio.__file__).parent.glob("*.py"))


@pytest.mark.parametrize("modulo", MODULOS_DO_DOMINIO, ids=lambda p: p.name)
def test_nenhum_modulo_do_dominio_le_o_relogio(modulo):
    """A regra do topo de saude.py, conferida lendo o codigo — e de TODO o dominio.

    Comecou so sobre saude.py. A maquina do ciclo (T5) e a segunda a receber o
    relogio por parametro, e um segundo verificador igual para ela seria o mesmo
    trabalho em dois lugares. A lista de modulos e derivada da pasta: modulo novo
    entra sozinho.

    Combinar ("ninguem chama now() aqui") e o que falha em silencio: passa hoje e
    reprova em outro segundo, em outro fuso, na virada do horario de verao. Pega
    tambem o apelido — `from datetime import datetime as dt; dt.now()` chega
    pelo atributo.

    O que isto NAO pega: `getattr(datetime, "now")`. E ofuscacao deliberada, e
    nao e o erro que se comete sem perceber.
    """
    assert _leituras_de_relogio(ast.parse(modulo.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize(
    "trecho",
    [
        "from datetime import datetime\nx = datetime.now()",
        "from datetime import datetime as dt\nx = dt.utcnow()",
        "import datetime\nx = datetime.date.today()",
        "import time\nx = time.time()",
        "from time import monotonic",
        "import time as t",
    ],
)
def test_o_verificador_pega_cada_forma(trecho):
    """O verificador tem que reprovar, senao ele e combinado com cara de verificado."""
    assert _leituras_de_relogio(ast.parse(trecho)) != []


def test_degradada_nao_e_campo_em_lugar_nenhum_do_dominio():
    """`degradada` e calculada, nunca guardada — invariante da spec.

    Varre o pacote inteiro, e nao so este modulo: o campo tentador nasceria no
    estado do ciclo ou na VM protegida, por conveniencia, e nao aqui.
    """
    raiz = Path(dominio.__file__).parent
    guardados = []
    for arquivo in raiz.glob("*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            alvos = []
            if isinstance(no, ast.AnnAssign):
                alvos = [no.target]
            elif isinstance(no, ast.Assign):
                alvos = list(no.targets)
            for alvo in alvos:
                nome = alvo.attr if isinstance(alvo, ast.Attribute) else getattr(alvo, "id", "")
                if "degradad" in nome.lower():
                    guardados.append(f"{arquivo.name}:{no.lineno} {nome}")
    assert guardados == []


def test_o_parametro_nao_sombreia_a_funcao_do_modulo():
    """Com o parametro chamado `idade_do_ponto`, a funcao homonima ficava
    inalcancavel dentro de `esta_degradada`, e o erro nao sugeria a causa."""
    import inspect

    assert "idade_do_ponto" not in inspect.signature(esta_degradada).parameters


# ── degradada nao vira coluna ───────────────────────────────────────────────

MIGRACOES = Path(__file__).resolve().parents[2] / "deploy" / "migrations"


def _colunas_degradadas(sql: str) -> list[str]:
    """Todo identificador SQL que nomeie degradada — coluna, view ou indice.

    Estrito de proposito: nenhuma migracao precisa do nome, entao falso positivo
    custa renomear, e falso negativo custa a segunda fonte de verdade.
    """
    # Sem `\b`: o sublinhado e caractere de palavra, entao `\b` nao separa
    # `vm_` de `degradadas`, e o nome no meio de um identificador passava.
    return re.findall(r"degradad\w*", sql, re.IGNORECASE)


def test_degradada_nao_e_coluna_em_migracao_nenhuma():
    """O risco que o plano dizia conter com "o plano ja diz" — intencao, e nao
    mecanismo. O meta-checador pegou isso na primeira execucao.

    A resposta a "liste as VMs degradadas" e view ou expressao computada, nao
    coluna: a partir da coluna existem duas fontes de verdade que podem
    discordar. Uma view chamada `vm_saude` com a conta dentro passa aqui; uma
    coluna `degradada` nao.
    """
    assert MIGRACOES.is_dir()
    achados = {
        arquivo.name: _colunas_degradadas(arquivo.read_text(encoding="utf-8"))
        for arquivo in sorted(MIGRACOES.glob("*.sql"))
    }
    assert {nome: nomes for nome, nomes in achados.items() if nomes} == {}


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE vm_protegida ADD COLUMN degradada boolean;",
        "CREATE TABLE x (id uuid, Degradada BOOLEAN NOT NULL);",
        "CREATE INDEX vm_degradadas ON vm_protegida (id);",
    ],
)
def test_o_detector_de_coluna_pega_cada_forma(sql):
    """Detector que nunca reprovou e combinado com cara de verificado."""
    assert _colunas_degradadas(sql)
