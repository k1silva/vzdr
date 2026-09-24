-- core-001 — isolamento de tenant por Row Level Security (ADR-0006).
--
-- A migracao anterior poe tenant_id nas tabelas. Isso torna o isolamento
-- POSSIVEL, nao garantido: a coluna existe, resta alguem usa-la em toda
-- consulta. Esta migracao e o que transforma disciplina em propriedade.
--
-- Escrito tabela por tabela, sem laco, de proposito: e controle de seguranca,
-- e quem revisa precisa ler cada politica inteira sem desdobrar `format()`.
--
-- Tres pontos que nao sao detalhe:
--
-- 1. FORCE, e nao so ENABLE. Sem FORCE o dono da tabela ignora a politica — e
--    o dono e justamente quem roda as migracoes. Protecao que o caminho mais
--    provavel de administracao nao respeita e pior que nenhuma, porque da
--    confianca.
-- 2. `nullif(..., '')`. Sem contexto, current_setting devolve NULL, a
--    comparacao da NULL, e a consulta devolve ZERO LINHA em vez de vazar.
--    String vazia tambem vira NULL, senao o cast para uuid explodiria com uma
--    mensagem que nao se parece com o problema.
-- 3. `with check` explicito, embora hoje redundante. O Postgres usa a
--    expressao de `using` tambem como verificacao de escrita quando `with
--    check` e omitido, entao a protecao de escrita existiria de qualquer jeito
--    — isto foi comprovado removendo a clausula e vendo os testes passarem.
--    Ela fica escrita porque as duas deixam de ser a mesma coisa no dia em que
--    `using` for afrouxado (um catalogo compartilhado, por exemplo). Sem a
--    clausula, afrouxar a leitura afrouxaria a escrita junto, em silencio.
--
-- O contexto entra com set_config('vzdr.tenant_id', <id>, true) — o `true` e o
-- `LOCAL`, que amarra o valor a transacao. Sem ele o valor gruda na conexao,
-- volta ao pool e atende a requisicao seguinte, de outro tenant.

alter table associacao_tenant enable row level security;
alter table associacao_tenant force row level security;

create policy isolamento_por_tenant on associacao_tenant
    using (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid)
    with check (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid);

alter table sessao enable row level security;
alter table sessao force row level security;

create policy isolamento_por_tenant on sessao
    using (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid)
    with check (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid);

alter table token_servico enable row level security;
alter table token_servico force row level security;

create policy isolamento_por_tenant on token_servico
    using (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid)
    with check (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid);

alter table auditoria enable row level security;
alter table auditoria force row level security;

create policy isolamento_por_tenant on auditoria
    using (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid)
    with check (tenant_id = nullif(current_setting('vzdr.tenant_id', true), '')::uuid);
