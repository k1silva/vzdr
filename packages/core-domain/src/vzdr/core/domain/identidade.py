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
from typing import Optional, Union
from uuid import UUID

__all__ = [
    "DiscoInvalidoError",
    "Especie",
    "Leitura",
    "NomeDeCiclo",
    "NomeNossoIlegivel",
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
    """Nome nosso, de especie que esta versao interpreta.

    `disco` so existe no export, e e obrigatorio nele. Bitmap e checkpoint nao o
    tem, e pelo motivo oposto em cada um — ver `nome_de`.
    """

    especie: Especie
    ciclo_id: UUID
    disco: Optional[str] = None


@dataclass(frozen=True)
class NomeNossoIlegivel:
    """Nosso pela forma, com especie que esta versao nao interpreta.

    Versoes diferentes convivendo no mesmo parque e estado normal, nao acidente —
    e a premissa que faz "versao do contrato nao e campo" depender de recusa por
    desconhecimento, em docs/adr/0015-efeito-como-valor.md.

    Nao tocar, e **reportar**. Colapsar isto em "nao e nosso" seria valor
    desconhecido virando padrao, que e a regra que o ADR-0015 proibe — e o custo
    esta escrito no topo deste modulo: orfao que fica para sempre, em silencio, e
    o ciclo seguinte colide com ele.
    """

    especie_crua: str
    ciclo_id: UUID


#: Os tres estados do dominio. `None` e "nao e nosso".
#:
#: Sao tres porque a acao e diferente em cada um, e `Optional[NomeDeCiclo]` so
#: expressa dois. O terceiro nao e erro nem excecao: e divergencia, e quem
#: reconcilia a trata como trata as outras.
Leitura = Union[NomeDeCiclo, NomeNossoIlegivel, None]


class DiscoInvalidoError(ValueError):
    """Disco que o leitor nao conseguiria ler de volta.

    O escritor recusa o que o leitor recusaria. Se `nome_do_export` aceitasse
    qualquer texto, um alvo de disco com caractere fora de `[a-z0-9]` produziria
    um nome que `ler_nome` devolveria como "nao e nosso" — a pior das respostas,
    porque e nao limpar orfao nosso. E a assimetria de sempre, no sentido
    contrario: aqui o escritor aceitava o que o leitor recusa.
    """


#: Alvo de disco como a libvirt o nomeia: `vda`, `vdb`, `sda`, `nvme0n1`. Sem
#: hifen, porque o hifen e o separador do nome — com ele, `vzdr-exp-<hex>-a-b`
#: teria duas leituras.
_DISCO = re.compile(r"[a-z0-9]+")

# 32 digitos hexadecimais minusculos: e o `UUID.hex`, sem hifens.
#
# Minusculo e exigencia, nao estilo. Aceitar maiusculo faria dois nomes
# diferentes mapearem para o mesmo ciclo, e "orfao e nome cujo ciclo nao esta
# ativo" deixaria de ser uma definicao para virar uma consulta com empate.
#
# `fullmatch`, e sem `^...$`: em Python o `$` casa TAMBEM antes de uma quebra de
# linha final, entao `vzdr-bmp-<hex>\n` passava por nosso. Nome chega de saida de
# comando, e saida de comando termina em `\n` — o defeito nao seria raro, e o
# preco dele e tratar como nosso um nome que nao e exatamente o nosso.
_LEITOR = re.compile(
    re.escape(PREFIXO) + r"-(?P<especie>[a-z]{3})-(?P<ciclo>[0-9a-f]{32})(?:-(?P<disco>[a-z0-9]+))?"
)

#: Quais especies levam disco no nome. So o export.
#:
#: - export: um por disco, e o R5 da dr-006 poe todos os discos de uma VM na
#:   MESMA receptora — o mesmo servidor NBD. O NBD escolhe export por nome, entao
#:   dois exports do mesmo ciclo com o mesmo nome no mesmo servidor sao
#:   impossiveis: o segundo `block-export-add` falha.
#: - checkpoint: e da VM, criado numa chamada so sobre todos os discos. Um nome
#:   por ciclo e o certo.
#: - bitmap temporario: o QEMU separa nomes de bitmap por no de bloco, entao o
#:   mesmo nome em cada disco nao colide.
_COM_DISCO = frozenset({Especie.EXPORT})


def nome_de(especie: Especie, ciclo_id: UUID, disco: Optional[str] = None) -> str:
    """O nome de uma especie para um ciclo — e, no export, para um disco.

    Deterministico: os mesmos argumentos sempre produzem a mesma string, em
    qualquer processo e em qualquer execucao. E o que permite o agente
    reencontrar o recurso depois de um reinicio, sem guardar nada.

    Disco onde nao cabe, ou falta onde e obrigatorio, e recusa: o nome sairia
    num formato que `ler_nome` nao devolve como nosso.
    """
    if especie in _COM_DISCO:
        if disco is None:
            raise DiscoInvalidoError(f"{especie.name} exige o disco no nome")
        if not _DISCO.fullmatch(disco):
            raise DiscoInvalidoError(
                f"disco {disco!r} fora de [a-z0-9]: o nome sairia num formato que "
                "ler_nome nao reconheceria como nosso, e o orfao nao seria limpo"
            )
        return f"{PREFIXO}-{especie.value}-{ciclo_id.hex}-{disco}"
    if disco is not None:
        raise DiscoInvalidoError(f"{especie.name} e por ciclo, e nao leva disco no nome")
    return f"{PREFIXO}-{especie.value}-{ciclo_id.hex}"


def nome_do_bitmap(ciclo_id: UUID) -> str:
    """O bitmap temporario do ciclo — o mesmo nome em cada disco, e nao colide."""
    return nome_de(Especie.BITMAP, ciclo_id)


def nome_do_checkpoint(ciclo_id: UUID) -> str:
    """O checkpoint que o ciclo cria, um so para a VM inteira.

    E tambem o nome do BITMAP desse checkpoint, em cada disco: o libvirt nomeia o
    bitmap exatamente como o checkpoint, o mesmo nome em todos os discos que
    recebem bitmap (medido na M5, libvirt 9.5.0 da VHI). Por isso o bitmap de um
    checkpoint e lido por `ler_nome` como especie CHECKPOINT, e nao BITMAP.

    E e a EVIDENCIA de que so o export pode levar o disco no nome: um nome de
    bitmap por disco seria inescrevivel pelo libvirt. O desenho acertou uma
    restricao antes de ela ser medida — quem quiser "melhorar" o esquema pondo o
    disco aqui esbarra nela.
    """
    return nome_de(Especie.CHECKPOINT, ciclo_id)


def nome_do_export(ciclo_id: UUID, disco: str) -> str:
    """O export publicado no destino, por ciclo E por disco.

    Por ciclo, e nao so por disco: com nome por disco, um cercamento atrasado
    derrubaria o export do ciclo seguinte (emenda ao R3 da dr-006).

    E por disco, e nao so por ciclo: o R5 da dr-006 poe os discos de uma VM na
    mesma receptora, e o NBD nao aceita dois exports com o mesmo nome no mesmo
    servidor. A primeira versao desta funcao nao recebia o disco, e numa VM de
    dois discos o segundo `block-export-add` falharia.
    """
    return nome_de(Especie.EXPORT, ciclo_id, disco)


def ler_nome(nome: str) -> Leitura:
    """Le um nome, e diz em qual dos tres estados ele esta.

    - `None` — nao e nosso. `tmp1`, `dr-1727280000`, um bitmap que o cliente
      mantem por conta dele. Nao tocar.
    - `NomeDeCiclo` — nosso, especie conhecida e forma certa para ela. Candidato
      a orfao.
    - `NomeNossoIlegivel` — nosso pela forma geral, mas que esta versao nao
      interpreta: especie desconhecida, ou especie conhecida com o disco onde nao
      cabe ou faltando onde e obrigatorio. Nao tocar **e** reportar. Um export
      sem disco e exatamente o nome que a versao anterior desta funcao produzia.

    Nada aqui levanta excecao: nome alheio e o caso COMUM numa varredura de
    hypervisor, e excecao empurraria quem varre a envolver cada nome num `try`.
    """
    casou = _LEITOR.fullmatch(nome)
    if casou is None:
        return None
    crua = casou.group("especie")
    ciclo_id = UUID(hex=casou.group("ciclo"))
    disco = casou.group("disco")
    try:
        especie = Especie(crua)
    except ValueError:
        return NomeNossoIlegivel(especie_crua=crua, ciclo_id=ciclo_id)
    if (especie in _COM_DISCO) != (disco is not None):
        return NomeNossoIlegivel(especie_crua=crua, ciclo_id=ciclo_id)
    return NomeDeCiclo(especie=especie, ciclo_id=ciclo_id, disco=disco)
