"""Quem esta pedindo, em nome de qual tenant, e o que pode fazer.

Puro: sem IO, sem banco, sem rede. A autenticacao produz um `Principal`; a
autorizacao decide sobre ele com `pode()`. Nada mais atravessa a fronteira.

Duas propriedades valem a pena ser explicitas, porque sao de seguranca:

- `pode()` e funcao de um valor imutavel. Nao consulta nada. O `Principal` e
  resolvido uma vez por requisicao, na borda, e viaja como valor — resolver o
  papel a cada verificacao e que seria gargalo, nao a autenticacao.
- Principal de plataforma nao pode nenhuma acao de tenant. E a segunda
  invariante de specs/core-001-tenancy/spec.md: um papel que enxerga tudo
  transforma o isolamento em teatro.

Este modulo roda no hypervisor (fecho de 3.9, ADR-0007): sem sintaxe 3.10+.
"""

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

__all__ = [
    "ACOES_DE_PLATAFORMA",
    "ACOES_DE_TENANT",
    "Acao",
    "Origem",
    "Papel",
    "Principal",
    "PrincipalInvalidoError",
    "e_destrutiva",
    "pode",
]


class Origem(str, enum.Enum):
    """De onde veio a autoridade."""

    USUARIO = "usuario"
    SERVICO = "servico"


class Papel(str, enum.Enum):
    """Papel dentro de um tenant. O papel de plataforma nao esta aqui: ele
    existe fora do eixo de tenant, e e o campo `plataforma` do principal."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class Acao(str, enum.Enum):
    """O que se pede para fazer.

    Acao nova entra em ACOES_DE_TENANT ou em ACOES_DE_PLATAFORMA, e o teste de
    cobertura falha enquanto nao entrar. E deliberado: acao sem eixo definido
    cairia no `False` do fim de `pode()` e pareceria um bug de permissao.
    """

    LER = "ler"
    CONFIGURAR_PROTECAO = "configurar_protecao"
    RODAR_TEST_FAILOVER = "rodar_test_failover"
    DISPARAR_FAILOVER = "disparar_failover"
    GERIR_USUARIOS = "gerir_usuarios"
    GERIR_TENANTS = "gerir_tenants"
    VER_SAUDE = "ver_saude"


#: Acontecem dentro de um tenant e exigem papel naquele tenant.
ACOES_DE_TENANT = frozenset(
    {
        Acao.LER,
        Acao.CONFIGURAR_PROTECAO,
        Acao.RODAR_TEST_FAILOVER,
        Acao.DISPARAR_FAILOVER,
        Acao.GERIR_USUARIOS,
    }
)

#: Nao acontecem dentro de tenant nenhum. So o papel de plataforma as faz.
ACOES_DE_PLATAFORMA = frozenset({Acao.GERIR_TENANTS, Acao.VER_SAUDE})

#: Exigem confirmacao humana explicita e papel `admin` (P6), mesmo quando o
#: pedido chega por token de servico — inclusive de um assistente de IA.
ACOES_DESTRUTIVAS = frozenset({Acao.DISPARAR_FAILOVER})

_PERMISSOES: Mapping[Papel, frozenset[Acao]] = {
    Papel.VIEWER: frozenset({Acao.LER}),
    Papel.OPERATOR: frozenset(
        {
            Acao.LER,
            Acao.CONFIGURAR_PROTECAO,
            Acao.RODAR_TEST_FAILOVER,
        }
    ),
    # Disparar failover e gerir usuarios sao do admin: um e destrutivo e decide
    # negocio, o outro muda quem pode o que.
    Papel.ADMIN: ACOES_DE_TENANT,
}


class PrincipalInvalidoError(Exception):
    """Combinacao de campos que nao corresponde a nenhum principal legitimo."""


@dataclass(frozen=True)
class Principal:
    """Uma identidade ja resolvida, com tenant e papel.

    As tres formas legitimas estao nos construtores. O `__post_init__` recusa
    o resto: um principal de plataforma com `tenant_id`, por exemplo, seria
    exatamente o atalho que a spec proibe.
    """

    origem: Origem
    usuario_id: UUID
    servico_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    papel: Optional[Papel] = None
    plataforma: bool = False

    def __post_init__(self) -> None:
        if (self.origem is Origem.SERVICO) != (self.servico_id is not None):
            raise PrincipalInvalidoError("servico_id existe se, e somente se, a origem e servico")
        if self.plataforma:
            if self.tenant_id is not None or self.papel is not None:
                raise PrincipalInvalidoError(
                    "principal de plataforma nao tem tenant ativo nem papel de "
                    "tenant: ele nao tem onde carregar um tenant_id"
                )
        elif self.tenant_id is None or self.papel is None:
            raise PrincipalInvalidoError(
                "principal de tenant precisa de tenant_id e papel resolvido"
            )

    @classmethod
    def de_usuario(cls, usuario_id: UUID, tenant_id: UUID, papel: Papel) -> "Principal":
        return cls(
            origem=Origem.USUARIO,
            usuario_id=usuario_id,
            tenant_id=tenant_id,
            papel=papel,
        )

    @classmethod
    def de_servico(
        cls, usuario_dono_id: UUID, servico_id: UUID, tenant_id: UUID, papel: Papel
    ) -> "Principal":
        """Token de servico: mesmo tenant e mesmo papel do dono, nunca mais.

        O papel chega ja resolvido de `associacao_tenant`, nunca congelado na
        emissao — rebaixar o dono rebaixa o token no uso seguinte.
        """
        return cls(
            origem=Origem.SERVICO,
            usuario_id=usuario_dono_id,
            servico_id=servico_id,
            tenant_id=tenant_id,
            papel=papel,
        )

    @classmethod
    def de_plataforma(cls, usuario_id: UUID) -> "Principal":
        return cls(origem=Origem.USUARIO, usuario_id=usuario_id, plataforma=True)


def pode(principal: Principal, acao: Acao) -> bool:
    """Se este principal pode esta acao. Total, pura, e fecha negando.

    Nao ha caso especial para token de servico: ele chega com o tenant e o
    papel do dono, entao decidir sobre ele e decidir sobre o dono. E assim que
    "o servico nunca excede o dono" deixa de depender de lembrar.
    """
    if principal.plataforma:
        return acao in ACOES_DE_PLATAFORMA
    if acao in ACOES_DE_PLATAFORMA:
        # Papel de tenant nao gere tenants nem ve a saude do sistema.
        return False
    if principal.papel is None:  # pragma: no cover - barrado no __post_init__
        return False
    return acao in _PERMISSOES[principal.papel]


def e_destrutiva(acao: Acao) -> bool:
    """Se a acao exige confirmacao humana explicita e auditoria (P6)."""
    return acao in ACOES_DESTRUTIVAS
