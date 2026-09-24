-- core-001 — a sessao viva morre quando o papel no tenant e revogado.
--
-- Assimetria acidental da migracao 0001, encontrada na revisao da T11:
-- `token_servico` ganhou chave composta para `(usuario_id, tenant_id)` de
-- `associacao_tenant`, justamente para que perder o papel derrubasse o token.
-- `sessao` nao ganhou. O resultado era que tirar o papel de alguem num tenant
-- matava o token de servico na hora e deixava a sessao interativa valendo ate
-- expirar — ate doze horas de acesso a um tenant de onde a pessoa foi removida.
--
-- Nao havia motivo para a diferenca. Sessao interativa e token de servico
-- carregam a mesma autoridade; se o papel some, os dois somem.
--
-- A mesma chave composta resolve, e a garantia sai do codigo para o esquema
-- pela quarta vez nesta fatia. Verificacao de integridade referencial ignora
-- RLS, entao o cascade alcanca a sessao mesmo quem revoga estando noutro
-- contexto.
--
-- As chaves individuais para `usuarios` e `tenants` ficam: elas dao erro mais
-- claro para o engano mais simples, e a redundancia nao custa correcao.

alter table sessao
    add constraint sessao_exige_associacao
    foreign key (usuario_id, tenant_id)
    references associacao_tenant (usuario_id, tenant_id)
    on delete cascade;
