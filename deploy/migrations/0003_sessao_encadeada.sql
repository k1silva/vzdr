-- core-001 — a expiracao da sessao filha passa a ser garantida pelo banco.
--
-- Trocar de tenant cria uma sessao a partir de outra. A regra e que a filha
-- expire JUNTO com a mae, nunca depois: sem isso, alternar entre tenants
-- renovaria o relogio a cada salto e a sessao duraria para sempre.
--
-- A garantia e uma chave estrangeira composta, e nao um gatilho. O gatilho
-- rodaria no contexto do tenant de DESTINO, onde a linha da mae esta escondida
-- pela RLS, e so funcionaria como `security definer` — a superficie
-- privilegiada que esta spec ja recusou tres vezes. A chave composta nao
-- precisa de codigo nenhum.
--
-- Ela garante IGUALDADE, nao "nao depois", que e a leitura certa de "herda,
-- nunca estende".
--
-- `on update cascade` tem motivo: a chave trava o `expira_em` da mae, entao
-- qualquer `update` nele violaria a referencia das filhas. A spec nao descarta
-- renovacao de sessao, e quando ela existir o certo e renovar a cadeia junto.
--
-- Isto funciona atravessando tenants — a filha vive no destino e aponta para a
-- mae na origem — porque verificacao de integridade referencial ignora RLS no
-- PostgreSQL. E o que faz o cascade alcancar descendentes em outros tenants.

alter table sessao drop constraint sessao_sessao_pai_id_fkey;

-- Alvo da chave composta. `id` ja e chave primaria, entao isto nao restringe
-- nada novo: so da a `(id, expira_em)` a unicidade que a referencia exige.
alter table sessao add constraint sessao_id_expira_em_unico unique (id, expira_em);

alter table sessao
    add constraint sessao_herda_expiracao
    foreign key (sessao_pai_id, expira_em)
    references sessao (id, expira_em)
    on delete cascade
    on update cascade;
