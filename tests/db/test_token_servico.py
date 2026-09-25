"""Token de serviço: o papel é lido na hora, nunca congelado.

O teste que mais importa aqui é o do **rebaixamento**. A chave composta do
esquema já cobre "associação some, token morre", e continuaria passando com o
papel congelado na linha do token — cobertura aparente. O que tira a autoridade
no caso comum, que é o papel mudar, é a leitura a cada resolução.
"""

import hashlib
import uuid
from datetime import timedelta

import pytest

from vzdr.core.audit import registrar
from vzdr.core.domain.tenancy import Acao, Origem, Papel, Principal, pode
from vzdr.core.tenancy.autenticacao import TokenInvalidoError, VerificadorLocal
from vzdr.core.tenancy.repositorio import Repositorio
from vzdr.core.tenancy.servico import JANELA_DE_USO, resolver

pytestmark = pytest.mark.db


def emitir(conexao, tenant, dono, descricao="cli"):
    """Emite um token de serviço à mão: criar é de `core-007`."""
    token = f"{tenant}.{uuid.uuid4().hex}"
    with conexao.cursor() as cur:
        cur.execute(
            "insert into token_servico (token_hash, usuario_dono_id, tenant_id, descricao) "
            "values (%s, %s, %s, %s) returning id",
            (hashlib.sha256(token.encode()).hexdigest(), dono, tenant, descricao),
        )
        return token, cur.fetchone()[0]


@pytest.fixture()
def conta(conexao, esquema_migrado):  # noqa: ARG001 - precisa da migração aplicada
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values ('a', %s) returning id",
            (f"a-{uuid.uuid4().hex[:8]}",),
        )
        (tenant,) = cur.fetchone()
        cur.execute(
            "insert into usuarios (email, senha_hash, senha_params) "
            "values (%s,'h','p') returning id",
            (f"{uuid.uuid4().hex[:8]}@exemplo.test",),
        )
        (dono,) = cur.fetchone()
        cur.execute(
            "insert into associacao_tenant (usuario_id, tenant_id, papel) values (%s, %s, 'admin')",
            (dono, tenant),
        )
    return tenant, dono


def papel_do_dono(conexao, dono, tenant, papel):
    with conexao.cursor() as cur:
        cur.execute(
            "update associacao_tenant set papel = %s where usuario_id = %s and tenant_id = %s",
            (papel, dono, tenant),
        )


def test_resolve_para_o_dono_e_o_tenant(conexao, conta):
    tenant, dono = conta
    token, servico_id = emitir(conexao, tenant, dono)
    principal = resolver(conexao, token)

    assert principal.origem is Origem.SERVICO
    assert principal.usuario_id == dono
    assert principal.servico_id == servico_id
    assert principal.tenant_id == tenant
    assert principal.papel is Papel.ADMIN


# --------------------------------------------------------------------------
# O caso que a chave composta NÃO cobre: o papel muda, a associação fica.
# --------------------------------------------------------------------------


def test_rebaixar_o_dono_rebaixa_o_mesmo_token(conexao, conta):
    """A associação continua existindo, a chave não dispara, e é a leitura na
    resolução que tira a autoridade."""
    tenant, dono = conta
    token, _ = emitir(conexao, tenant, dono)
    assert resolver(conexao, token).papel is Papel.ADMIN

    papel_do_dono(conexao, dono, tenant, "viewer")
    assert resolver(conexao, token).papel is Papel.VIEWER


def test_a_acao_que_exigia_admin_passa_a_ser_negada(conexao, conta):
    """O efeito que importa, não só o campo: o token deixa de poder."""
    tenant, dono = conta
    token, _ = emitir(conexao, tenant, dono)
    assert pode(resolver(conexao, token), Acao.DISPARAR_FAILOVER) is True

    papel_do_dono(conexao, dono, tenant, "operator")
    assert pode(resolver(conexao, token), Acao.DISPARAR_FAILOVER) is False
    assert pode(resolver(conexao, token), Acao.RODAR_TEST_FAILOVER) is True


def test_a_associacao_continua_existindo_apos_o_rebaixamento(conexao, conta):
    """Prova que a chave composta não foi quem agiu — se tivesse agido, a
    linha teria sumido e este teste não distinguiria as duas causas."""
    tenant, dono = conta
    emitir(conexao, tenant, dono)
    papel_do_dono(conexao, dono, tenant, "viewer")
    with conexao.cursor() as cur:
        cur.execute("select count(*) from token_servico")
        assert cur.fetchone() == (1,)


def test_o_papel_nao_mora_na_linha_do_token(conexao, conta):
    """Se alguém 'otimizar' guardando o papel aqui, este teste cai."""
    tenant, dono = conta
    emitir(conexao, tenant, dono)
    with conexao.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns where table_name = 'token_servico'"
        )
        colunas = {linha[0] for linha in cur.fetchall()}
    assert "papel" not in colunas


def test_perder_a_associacao_derruba_o_token(conexao, conta):
    """O caso extremo, garantido pelo esquema desde a T6a."""
    tenant, dono = conta
    token, _ = emitir(conexao, tenant, dono)
    with conexao.cursor() as cur:
        cur.execute(
            "delete from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (dono, tenant),
        )
    with pytest.raises(TokenInvalidoError):
        resolver(conexao, token)


# --------------------------------------------------------------------------
# ultimo_uso_em.
# --------------------------------------------------------------------------


def uso(conexao, servico_id):
    with conexao.cursor() as cur:
        cur.execute("select ultimo_uso_em from token_servico where id = %s", (servico_id,))
        return cur.fetchone()[0]


def test_a_primeira_resolucao_carimba_o_uso(conexao, conta):
    tenant, dono = conta
    token, servico_id = emitir(conexao, tenant, dono)
    assert uso(conexao, servico_id) is None
    resolver(conexao, token)
    assert uso(conexao, servico_id) is not None


def test_resolucao_seguinte_nao_carimba_de_novo(conexao, conta):
    """Gravar a cada resolução tornaria o caminho de leitura mais quente do
    sistema um caminho de escrita, por precisão que ninguém usa."""
    tenant, dono = conta
    token, servico_id = emitir(conexao, tenant, dono)
    resolver(conexao, token)
    primeiro = uso(conexao, servico_id)
    resolver(conexao, token)
    assert uso(conexao, servico_id) == primeiro


def test_carimba_de_novo_quando_o_valor_envelhece(conexao, conta):
    tenant, dono = conta
    token, servico_id = emitir(conexao, tenant, dono)
    resolver(conexao, token)
    with conexao.cursor() as cur:
        cur.execute(
            "update token_servico set ultimo_uso_em = now() - %s where id = %s",
            (JANELA_DE_USO + timedelta(minutes=1), servico_id),
        )
        cur.execute("select ultimo_uso_em from token_servico where id = %s", (servico_id,))
        (velho,) = cur.fetchone()
    resolver(conexao, token)
    assert uso(conexao, servico_id) > velho


def test_resolucao_recusada_nao_carimba(conexao, conta):
    """O campo responde "apresentado E resolveu com sucesso". Campo de
    segurança ambíguo é pior que campo ausente."""
    tenant, dono = conta
    token, servico_id = emitir(conexao, tenant, dono)
    papel_do_dono(conexao, dono, tenant, "viewer")
    with conexao.cursor() as cur:
        cur.execute(
            "delete from associacao_tenant where usuario_id = %s and tenant_id = %s",
            (dono, tenant),
        )
    with pytest.raises(TokenInvalidoError):
        resolver(conexao, token)
    with conexao.cursor() as cur:
        cur.execute("select count(*) from token_servico where id = %s", (servico_id,))
        assert cur.fetchone() == (0,)


# --------------------------------------------------------------------------
# Uma porta só, e a auditoria.
# --------------------------------------------------------------------------


def test_o_verificador_resolve_os_dois_tipos_de_token(conexao, conta):
    """Quem recebe um token não sabe de que tipo ele é; fazer a API escolher
    seria mais uma coisa para alguém lembrar."""
    tenant, dono = conta
    token, _ = emitir(conexao, tenant, dono)
    principal = VerificadorLocal(conexao).verificar(token)
    assert principal.origem is Origem.SERVICO
    assert principal.usuario_id == dono


def test_token_malformado_ou_desconhecido_e_recusado(conexao, conta):
    tenant, _ = conta
    for ruim in ("", "sem-ponto", "nao-e-uuid.x", f"{tenant}.nao-existe"):
        with pytest.raises(TokenInvalidoError):
            resolver(conexao, ruim)


def test_trocar_o_prefixo_nao_abre_nada(conexao, conta):
    tenant, dono = conta
    token, _ = emitir(conexao, tenant, dono)
    _, _, segredo = token.partition(".")
    with conexao.cursor() as cur:
        cur.execute(
            "insert into tenants (nome, identificador) values ('b', %s) returning id",
            (f"b-{uuid.uuid4().hex[:8]}",),
        )
        (outro,) = cur.fetchone()
    with pytest.raises(TokenInvalidoError):
        resolver(conexao, f"{outro}.{segredo}")


def test_a_auditoria_registra_servico_e_dono(conexao, conta):
    """P6 e P8: registrar só o serviço apaga de quem a autoridade foi
    emprestada — a pergunta de quando um assistente de IA agiu."""
    tenant, dono = conta
    token, servico_id = emitir(conexao, tenant, dono)
    principal = resolver(conexao, token)

    repo = Repositorio(conexao, principal)
    with repo.transacao() as r:
        registrar(r, "dr.ciclo_concluido", "vm:jau-server01")
        linhas = r.selecionar("auditoria", ["usuario_id", "servico_id", "autor"])

    assert linhas[0][0] == dono
    assert linhas[0][1] == servico_id
    assert "@" in linhas[0][2]


def test_o_token_nunca_excede_o_dono(conexao, conta):
    """Para toda ação, o serviço pode exatamente o que o dono pode."""
    tenant, dono = conta
    token, _ = emitir(conexao, tenant, dono)
    for papel in ("viewer", "operator", "admin"):
        papel_do_dono(conexao, dono, tenant, papel)
        servico = resolver(conexao, token)
        usuario = Principal.de_usuario(dono, tenant, Papel(papel))
        for acao in Acao:
            assert pode(servico, acao) is pode(usuario, acao)
