-- Dois papeis de banco, como o ADR-0006 exige.
--
-- Este arquivo roda so na PRIMEIRA subida do container (docker-entrypoint-initdb.d)
-- e vale so para o laboratorio local. Em producao os papeis sao criados pela
-- operacao, com senha que nao mora em repositorio.
--
-- `vzdr`      — dono das tabelas, roda as migracoes.
-- `vzdr_app`  — a aplicacao. Nao e dono e nao tem BYPASSRLS, que e o que faz a
--               politica de RLS valer para ela. Sem essa separacao, a rede de
--               protecao da RLS so existiria onde ninguem testa.

create role vzdr_app with login password 'dev' nobypassrls;
