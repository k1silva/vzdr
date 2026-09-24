"""Registrar o que aconteceu, na tabela certa.

Sao duas funcoes porque sao duas tabelas, e sao duas tabelas porque um
`tenant_id` nulavel faria uma consulta filtrada por tenant descartar ou incluir
linha de plataforma em silencio, conforme o `WHERE` — o buraco que P9 existe
para fechar. Com duas, o chamador escolhe, e a escolha errada aparece na
revisao.

Duas regras que valem sempre:

- **`usuario_id` e sempre o humano.** Em acao vinda de token de servico, e o
  dono do token. Registrar so o servico apaga de quem a autoridade foi
  emprestada — e essa e a pergunta que alguem faz as tres da manha quando um
  assistente de IA agiu (P6, P8).
- **A auditoria nao e reescrita.** A aplicacao tem `select` e `insert`, nunca
  `update` nem `delete` (migracao 0001). Corrigir log e reescrever historia.
- **O autor vai tambem em texto legivel.** Auditoria nao e autorizacao: sessao e
  token de servico devem morrer com a associacao, mas o registro historico tem
  que sobreviver a remocao de tudo que referencia — senao revogar alguem apaga
  a prova do que essa pessoa fez. Sobreviver nao basta: um uuid que nao aponta
  para lugar nenhum nao responde "quem fez". Por isso o e-mail do momento do ato
  e copiado, nunca referenciado (migracao 0005).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from psycopg import sql
from psycopg.types.json import Jsonb

from vzdr.core.domain.tenancy import Principal
from vzdr.core.tenancy.repositorio import Repositorio

if TYPE_CHECKING:
    import psycopg

    Conexao = psycopg.Connection[Any]


class PrincipalNaoEDePlataformaError(Exception):
    """Ato de plataforma pedido por principal de tenant.

    A tabela `auditoria_plataforma` registra o que nao acontece dentro de
    tenant nenhum. Deixar um principal de tenant escrever nela desfaria a
    separacao que as duas tabelas existem para manter.
    """


def _autor(cur: Any, usuario_id: Any) -> str | None:
    """O identificador legivel do autor, agora. Busca por chave primaria."""
    cur.execute("select email from usuarios where id = %s", (usuario_id,))
    linha = cur.fetchone()
    return str(linha[0]) if linha else None


def registrar(
    repositorio: Repositorio,
    evento: str,
    alvo: str,
    detalhe: Mapping[str, Any] | None = None,
) -> None:
    """Ato dentro de um tenant.

    Recebe o repositorio, e nao a conexao, porque e ele que carrega o principal
    e o tenant — e porque assim o `tenant_id` da linha vem do mesmo lugar que o
    filtro de toda consulta, nunca do chamador.
    """
    principal = repositorio.principal
    with repositorio.conexao.cursor() as cur:
        autor = _autor(cur, principal.usuario_id)
    repositorio.inserir(
        "auditoria",
        {
            "evento": evento,
            "usuario_id": principal.usuario_id,
            "servico_id": principal.servico_id,
            "autor": autor,
            "alvo": alvo,
            "detalhe": Jsonb(detalhe) if detalhe is not None else None,
        },
    )


def registrar_plataforma(
    conexao: Conexao,
    principal: Principal,
    evento: str,
    alvo: str,
    detalhe: Mapping[str, Any] | None = None,
) -> None:
    """Ato que nao acontece dentro de tenant nenhum: criar tenant, criar
    usuario, conceder papel."""
    if not principal.plataforma:
        raise PrincipalNaoEDePlataformaError(
            f"{evento} e ato de plataforma; principal de tenant registra em "
            f"`auditoria`, pela funcao registrar()"
        )

    consulta = sql.SQL(
        "insert into auditoria_plataforma "
        "(evento, usuario_id, servico_id, autor, alvo, detalhe) "
        "values (%s, %s, %s, %s, %s, %s)"
    )
    with conexao.cursor() as cur:
        cur.execute(
            consulta,
            (
                evento,
                principal.usuario_id,
                principal.servico_id,
                _autor(cur, principal.usuario_id),
                alvo,
                Jsonb(detalhe) if detalhe is not None else None,
            ),
        )
