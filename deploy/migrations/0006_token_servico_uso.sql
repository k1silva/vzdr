-- core-001 — quando este token foi usado pela ultima vez.
--
-- A pergunta que ele responde e operacional, nao estatistica: *posso revogar
-- este token sem quebrar nada?* Token de servico mora em arquivo de
-- configuracao e em CI, e quem revoga precisa saber se ainda ha alguem do outro
-- lado.
--
-- **Significado exato:** ultima vez que o token foi apresentado E resolveu com
-- sucesso. Nao e "apresentado". Token recusado — dono sem associacao, segredo
-- invalido — nao toca o campo. Campo de seguranca com significado ambiguo e
-- pior que campo ausente: o ausente faz procurar em outro lugar, o ambiguo faz
-- concluir errado.
--
-- `id` e `descricao` ja existem desde a 0001: sao o identificador visivel e o
-- rotulo legivel que a tela de `core-007` vai usar para listar e revogar sem
-- nunca ter o segredo.

alter table token_servico add column ultimo_uso_em timestamptz;

comment on column token_servico.ultimo_uso_em is
    'Ultima resolucao BEM SUCEDIDA. Gravado com granularidade de minutos.';
