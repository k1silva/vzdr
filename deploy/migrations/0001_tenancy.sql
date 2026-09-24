-- core-001 — tenancy e identidade.
--
-- P9: tenant_id em toda tabela que guarda dado de tenant. A lista fechada de
-- excecoes esta em specs/core-001-tenancy/spec.md e espelhada em
-- tests/invariants/check_tenant_id.py, com a justificativa de cada uma.
--
-- Duas separacoes desta migracao sao invariantes, nao arrumacao:
--   sessao / sessao_plataforma     — o principal de plataforma nao tem onde
--                                    carregar um tenant_id;
--   auditoria / auditoria_plataforma — ato de plataforma nao pode aparecer
--                                    como se tivesse acontecido num tenant.
--
-- RLS entra na migracao seguinte (ADR-0006).

create table tenants (
    id            uuid        primary key default gen_random_uuid(),
    nome          text        not null,
    identificador text        not null unique,
    criado_em     timestamptz not null default now()
);

-- Sem tenant_id: o vinculo vive em associacao_tenant, que pode ter mais de uma
-- linha por usuario. Papel e por tenant.
create table usuarios (
    id              uuid        primary key default gen_random_uuid(),
    email           text        not null,
    -- algoritmo + parametros + salt, nessa ordem. Quem valida le o algoritmo
    -- que a linha declara e nunca assume a politica atual.
    senha_hash      text        not null,
    senha_params    text        not null,
    -- Contador de falhas nasce aqui mesmo sem ninguem incrementar ainda:
    -- acrescentar coluna depois e migracao em tabela quente.
    falhas_de_senha integer     not null default 0,
    bloqueado_ate   timestamptz,
    criado_em       timestamptz not null default now()
);

create unique index usuarios_email_unico on usuarios (lower(email));

create table associacao_tenant (
    usuario_id uuid        not null references usuarios (id) on delete cascade,
    tenant_id  uuid        not null references tenants (id) on delete cascade,
    papel      text        not null check (papel in ('viewer', 'operator', 'admin')),
    criado_em  timestamptz not null default now(),
    primary key (usuario_id, tenant_id)
);

create index associacao_tenant_por_tenant on associacao_tenant (tenant_id);

-- Fora do eixo de tenant por definicao.
create table papel_plataforma (
    usuario_id uuid        primary key references usuarios (id) on delete cascade,
    criado_em  timestamptz not null default now()
);

create table sessao (
    id            uuid        primary key default gen_random_uuid(),
    token_hash    text        not null unique,
    usuario_id    uuid        not null references usuarios (id) on delete cascade,
    tenant_id     uuid        not null references tenants (id) on delete cascade,
    -- Sessao irma criada por troca de tenant. O cascade e o que faz revogar a
    -- mae revogar as filhas: sessao que sobrevive a que a originou e revogacao
    -- incompleta.
    sessao_pai_id uuid        references sessao (id) on delete cascade,
    expira_em     timestamptz not null,
    criada_em     timestamptz not null default now()
);

create index sessao_por_usuario on sessao (usuario_id, tenant_id);

-- Sem tenant_id: principal de plataforma nao tem tenant ativo. A FK para
-- papel_plataforma garante que so quem tem o papel ganha sessao de plataforma.
create table sessao_plataforma (
    id         uuid        primary key default gen_random_uuid(),
    token_hash text        not null unique,
    usuario_id uuid        not null references papel_plataforma (usuario_id) on delete cascade,
    expira_em  timestamptz not null,
    criada_em  timestamptz not null default now()
);

-- Guarda o dono e o tenant, nunca o papel: o papel vive so em
-- associacao_tenant, e e isso que faz rebaixar o dono rebaixar o token.
-- A FK composta faz mais: perder a associacao derruba o token junto.
create table token_servico (
    id              uuid        primary key default gen_random_uuid(),
    token_hash      text        not null unique,
    usuario_dono_id uuid        not null,
    tenant_id       uuid        not null,
    descricao       text        not null,
    criado_em       timestamptz not null default now(),
    foreign key (usuario_dono_id, tenant_id)
        references associacao_tenant (usuario_id, tenant_id) on delete cascade
);

create index token_servico_por_tenant on token_servico (tenant_id);

create table auditoria (
    id          uuid        primary key default gen_random_uuid(),
    tenant_id   uuid        not null references tenants (id),
    evento      text        not null,
    -- Sempre o humano. Em acao vinda de token de servico, e o dono: registrar
    -- so o servico apaga de quem a autoridade foi emprestada.
    usuario_id  uuid        not null,
    servico_id  uuid,
    alvo        text        not null,
    detalhe     jsonb,
    ocorrido_em timestamptz not null default now()
);

create index auditoria_por_tenant_e_tempo on auditoria (tenant_id, ocorrido_em desc);
create index auditoria_por_evento on auditoria (tenant_id, evento);

-- Sem tenant_id: registra atos que nao acontecem dentro de tenant nenhum —
-- criar tenant, criar usuario, conceder papel.
create table auditoria_plataforma (
    id          uuid        primary key default gen_random_uuid(),
    evento      text        not null,
    usuario_id  uuid        not null,
    servico_id  uuid,
    alvo        text        not null,
    detalhe     jsonb,
    ocorrido_em timestamptz not null default now()
);

create index auditoria_plataforma_por_tempo on auditoria_plataforma (ocorrido_em desc);
create index auditoria_plataforma_por_evento on auditoria_plataforma (evento);

-- Privilegios do papel da aplicacao. Ele nao e dono das tabelas e nao tem
-- BYPASSRLS — e o que fara a politica de RLS valer para ele (ADR-0006).
--
-- current_schema() em vez de `public` fixo: a suite de testes aplica esta
-- migracao num schema temporario, e um grant que ignora o search_path mentiria
-- sobre o que foi concedido.
do $$
declare
    esquema text := current_schema();
    tabela  text;
begin
    execute format('grant usage on schema %I to vzdr_app', esquema);

    foreach tabela in array array[
        'tenants', 'usuarios', 'associacao_tenant', 'papel_plataforma',
        'sessao', 'sessao_plataforma', 'token_servico'
    ]
    loop
        execute format(
            'grant select, insert, update, delete on %I.%I to vzdr_app',
            esquema, tabela
        );
    end loop;

    -- Auditoria e append-only para a aplicacao: sem update, sem delete.
    -- Corrigir log e reescrever historia; P8 depende de o registro ser o que
    -- aconteceu, nao o que alguem preferiu depois.
    foreach tabela in array array['auditoria', 'auditoria_plataforma']
    loop
        execute format(
            'grant select, insert on %I.%I to vzdr_app', esquema, tabela
        );
    end loop;
end $$;
