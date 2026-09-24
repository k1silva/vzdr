-- core-001 — a auditoria guarda o autor de forma legivel.
--
-- Auditoria nao e autorizacao, e a diferenca decide o esquema.
--
-- `sessao` e `token_servico` SAO autorizacoes vivas, e por isso ganharam chave
-- composta para `associacao_tenant`: perder o papel tem que derrubar as duas na
-- hora. Registro historico e o oposto — ele precisa SOBREVIVER a remocao de
-- tudo que referencia, senao revogar alguem apaga a prova do que essa pessoa
-- fez.
--
-- Por isso `auditoria.usuario_id` e `servico_id` nao tem chave estrangeira, e
-- isso esta certo. Mas sobreviver nao basta: o registro precisa continuar
-- LEGIVEL depois que a linha referenciada sumir. Hoje ele guarda so o uuid, e
-- um uuid que nao aponta para lugar nenhum nao responde "quem fez".
--
-- Entao cada linha guarda tambem o identificador do autor no momento do ato.
-- Copia, nao referencia: se o e-mail mudar depois, o registro continua dizendo
-- quem era na hora — que e a pergunta da auditoria.

alter table auditoria add column autor text;
alter table auditoria_plataforma add column autor text;

comment on column auditoria.autor is
    'Identificador legivel do autor no momento do ato. Copia, nunca referencia.';
comment on column auditoria_plataforma.autor is
    'Identificador legivel do autor no momento do ato. Copia, nunca referencia.';
