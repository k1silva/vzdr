"""Os nomes que um ciclo cria no hypervisor e no destino.

Nome que precisa ser *reconhecido depois* nao e infraestrutura, e identidade — e
identidade e do dominio. O formato da string e trivial; o que mora aqui e o
mapeamento ciclo -> nome, que e conhecimento.

Sao tres, e os tres tem a mesma razao de existir:

- **bitmap temporario.** O laboratorio usou `tmp1` cravado, e funcionou porque era
  um script, uma VM, uma execucao por vez. Em produto colide: ciclo que morreu
  deixa `tmp1` orfao, e o seguinte tenta criar um bitmap que ja existe.
- **checkpoint.** O laboratorio usou `dr-<timestamp>`, que colide se dois ciclos
  comecarem no mesmo segundo e nao carrega identidade nenhuma.
- **export no destino.** `block-export-del` derruba um export por nome. Com nome
  fixo por disco, um cercamento atrasado mata o job do ciclo seguinte em vez do
  zumbi — o cercamento funciona e cerca a coisa errada.

Com o nome derivado do ciclo, **orfao tem definicao**: nome cujo ciclo nao esta
ativo. A limpeza deixa de ser heuristica de prefixo, e cercar identifica a
instancia, nao o disco.

O ciclo e a unica coisa dita no nome. Tenant nao entra: o ciclo sabe de quem e, e
duas expressoes da mesma coisa podem discordar. Vale aqui a mesma regra do
envelope do efeito, em specs/dr-001-dominio-ciclo/spec.md.

Este modulo roda no hypervisor (fecho de 3.9, ADR-0007): sem sintaxe 3.10+.
"""

import enum
import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

__all__ = [
    "Especie",
    "NomeDeCiclo",
    "PREFIXO",
    "ler_nome",
    "nome_de",
    "nome_do_bitmap",
    "nome_do_checkpoint",
    "nome_do_export",
]

#: Marca o que e nosso. Sem ela nao ha como distinguir um recurso que criamos de
#: um que o cliente criou, e apagar o do cliente e falha critica (P1).
PREFIXO = "vzdr"


class Especie(enum.Enum):
    """O que o nome nomeia.

    O valor entra na string, entao e curto e estavel: mudar um destes renomeia
    recurso que ja existe no parque, e o ciclo seguinte nao reconhece o proprio
    orfao.
    """

    BITMAP = "bmp"
    CHECKPOINT = "ckp"
    EXPORT = "exp"


@dataclass(frozen=True)
class NomeDeCiclo:
    """O que um nome nosso diz, depois de lido."""

    especie: Especie
    ciclo_id: UUID


# 32 digitos hexadecimais minusculos: e o `UUID.hex`, sem hifens.
#
# Minusculo e exigencia, nao estilo. Aceitar maiusculo faria dois nomes
# diferentes mapearem para o mesmo ciclo, e "orfao e nome cujo ciclo nao esta
# ativo" deixaria de ser uma definicao para virar uma consulta com empate.
# `fullmatch`, e sem `^...$`: em Python o `$` casa TAMBEM antes de uma quebra de
# linha final, entao `vzdr-bmp-<hex>\n` passava por nosso. Nome chega de saida de
# comando, e saida de comando termina em `\n` — o defeito nao seria raro, e o
# preco dele e tratar como nosso um nome que nao e exatamente o nosso.
_LEITOR = re.compile(re.escape(PREFIXO) + r"-(?P<especie>[a-z]{3})-(?P<ciclo>[0-9a-f]{32})")


def nome_de(especie: Especie, ciclo_id: UUID) -> str:
    """O nome de uma especie para um ciclo.

    Deterministico: o mesmo par sempre produz a mesma string, em qualquer
    processo e em qualquer execucao. E o que permite o agente reencontrar o
    recurso depois de um reinicio, sem guardar nada.
    """
    return f"{PREFIXO}-{especie.value}-{ciclo_id.hex}"


def nome_do_bitmap(ciclo_id: UUID) -> str:
    """O bitmap temporario do ciclo."""
    return nome_de(Especie.BITMAP, ciclo_id)


def nome_do_checkpoint(ciclo_id: UUID) -> str:
    """O checkpoint que o ciclo cria."""
    return nome_de(Especie.CHECKPOINT, ciclo_id)


def nome_do_export(ciclo_id: UUID) -> str:
    """O export publicado no destino, por ciclo.

    Por ciclo, e nao por disco: com nome por disco, um cercamento atrasado
    derrubaria o export do ciclo seguinte. Ver a emenda ao R3 em
    specs/dr-006-provisionamento/spec.md.
    """
    return nome_de(Especie.EXPORT, ciclo_id)


def ler_nome(nome: str) -> Optional[NomeDeCiclo]:
    """Le um nome nosso; devolve `None` para qualquer outro.

    `None` e a resposta para tudo que nao criamos — `tmp1`, `dr-1727280000`, um
    bitmap que o cliente mantem por conta dele. Nao e caso de erro: e a
    distincao entre "orfao nosso, pode limpar" e "nao e nosso, nao toque".

    Devolver excecao aqui empurraria quem varre o hypervisor a envolver cada
    nome num `try`, e o caminho de nome alheio e o comum, nao o excepcional.
    """
    casou = _LEITOR.fullmatch(nome)
    if casou is None:
        return None
    try:
        especie = Especie(casou.group("especie"))
    except ValueError:
        # Prefixo nosso com especie que esta versao nao conhece. Pode ser um
        # agente mais novo no mesmo parque; nao e nosso para limpar.
        return None
    return NomeDeCiclo(especie=especie, ciclo_id=UUID(hex=casou.group("ciclo")))
