# core-001 — Tarefas

Cada tarefa cabe numa sessão de contexto e vira um commit.

Antes de cada uma: ler `spec.md`. Depois de cada uma: `make check`, e `make test-db`
quando a tarefa tocar banco. Teste junto com a implementação, nunca depois — inclusive o
caminho de falha.

- [ ] **T1** — Pasta `tests/db` e o alvo que a roda
  - Terceira pasta de teste, porque Postgres é outro eixo de infraestrutura que não
    libvirt. Marcador `db`, alvo `make test-db`, fora do `make check`.
  - Testes: um teste `db` trivial que conecta e falha com mensagem clara sem o banco
  - Arquivos: `tests/db/`, `Makefile`, `pyproject.toml`, `AGENTS.md`,
    `.github/workflows/ci.yml`

- [ ] **T2** — Executor de migração
  - Aplica `deploy/migrations/*.sql` em ordem, **um arquivo por transação**, gravando nome,
    SHA-256 e instante em `schema_migrations` na mesma transação. Arquivo já registrado é
    pulado; arquivo alterado depois de aplicado falha em vez de aplicar outra coisa.
  - Nunca roda sozinho fora do ambiente local (AGENTS.md), e o erro cru do Postgres vai
    para o log sem tradução (**P8**).
  - Testes: aplica duas vezes sem efeito; falha no meio de um arquivo não deixa esquema
    parcial (**P4**, mesma disciplina); conteúdo alterado é recusado; ordem respeitada
  - Arquivos: `scripts/migrar.py`, `tests/db/test_migrar.py`

- [ ] **T3** — Checador de `tenant_id` com lista fechada
  - `ISENTAS` vira mapa tabela → justificativa, espelhando a lista da spec. Exceção que
    nenhuma migração usa falha o build. Mensagem de erro cita a justificativa e o caminho
    da spec.
  - Corrige a spec junto: `alembic_version` sai, `schema_migrations` entra (já aplicado —
    conferir que o mapa e a tabela da spec batem linha a linha).
  - Vem **antes** da primeira migração de propósito: assim a migração nasce sob o checador.
  - Testes: tabela sem `tenant_id` falha; tabela isenta passa; exceção morta falha;
    mensagem contém a justificativa
  - Arquivos: `tests/invariants/check_tenant_id.py`, `tests/unit/test_check_tenant_id.py`

- [ ] **T4** — Domínio puro: `Principal` e `pode()`
  - `Origem`, `Papel`, `Acao`, `Principal` (frozen), `pode()`, `e_destrutiva()`. Sem IO,
    `mypy --strict`, sintaxe 3.9 (`Optional[X]`, nunca `X | Y`).
  - `pode()` devolve `False` para todo principal de plataforma em ação que toque dado de
    tenant — a segunda invariante da spec, exigível aqui e não só no SQL.
  - Testes: matriz inteira papel × ação, concedida e negada; plataforma negada em tudo que
    é de tenant; `pode()` não abre conexão (o checador de pureza já garante)
  - Arquivos: `packages/core-domain/src/vzdr/core/domain/tenancy.py`,
    `tests/unit/test_pode.py`

- [ ] **TI1** — Instalação editável dos pacotes no `make setup`
  - Tarefa de infraestrutura, não da spec. Fazer **logo depois** que a fatia T4+T5
    fechar, e antes de um terceiro pacote entrar.
  - Hoje há duas listas dos mesmos dez caminhos: `mypy_path` e `pythonpath`. É a mesma
    duplicação que quebrou a CI com o `psycopg` — dois lugares dizendo onde o projeto
    vive, e um deles vai desatualizar.
  - `make setup` instala cada `packages/*` em modo editável; `mypy_path` e `pythonpath`
    saem do `pyproject.toml`.
  - Testes: `pytest` e `mypy` acham `vzdr.*` sem as duas listas; pacote novo funciona
    sem editar configuração nenhuma
  - Arquivos: `Makefile`, `pyproject.toml`, `packages/*/pyproject.toml`

- [ ] **TI2** — Restringir `ignore_missing_imports` a terceiros *(candidata)*
  - Hoje ele é global em `[tool.mypy]`, o que faz **qualquer** import não resolvido virar
    `Any` em silêncio — inclusive `vzdr.*`. Foi o que tornou a ausência de `py.typed`
    invisível na TI1.
  - Passar a valer só para módulos de terceiros, por override, e deixar import interno
    não resolvido falhar.
  - Não fazer agora: mexer nisso provavelmente acende erros em cadeia, e merece uma fatia
    própria em vez de contaminar uma tarefa de produto.
  - Arquivos: `pyproject.toml`

- [ ] **TI3** — `check_eventos.py`: evento declarado tem que ser emitido
  - Todo evento nomeado numa spec ou numa `tasks.md` precisa ter emissor no código e
    teste que o exercite. Evento declarado e nunca emitido reprova o build.
  - Motivo: `tenancy.tenant_trocado` foi exigido pela T11 e não implementado, e **passou
    na revisão porque ninguém olha o que não está no diff**. Um diff não consegue mostrar
    ausência; nem quem escreve nem quem revisa alcança essa classe.
  - Testes: evento na spec sem emissor reprova; emissor sem teste reprova; evento emitido
    e testado passa; evento citado em prosa e não como nome de evento não conta
  - **Antes de a `core-001` fechar** — ela é a spec com mais eventos declarados.
  - Arquivos: `tests/invariants/check_eventos.py`, `tests/unit/test_check_eventos.py`

- [ ] **T5** — ADR-0006: isolamento de tenant com RLS
  - Decisão, alternativa (só repositório injetando filtro), e o custo real: `SET LOCAL` por
    transação, papel de banco sem `BYPASSRLS`, `FORCE ROW LEVEL SECURITY`.
  - Precede a migração porque é ela que implementa a decisão.
  - Arquivos: `docs/adr/0006-isolamento-por-rls.md`

- [ ] **T6** — Primeira migração: tabelas, índices, RLS
  - As oito tabelas do plano, mais `schema_migrations`. `tenant_id` onde a spec manda,
    ausente onde a spec isenta. Índices únicos de `token_hash` e `(usuario_id, tenant_id)`.
  - RLS com `FORCE` em toda tabela com `tenant_id`; papel de aplicação sem `BYPASSRLS`;
    sem `UPDATE`/`DELETE` concedidos nas tabelas de auditoria.
  - Colunas do contador de falha de senha já nascem aqui, mesmo sem ninguém incrementá-las:
    acrescentá-las depois é migração em tabela quente.
  - Testes: o checador de T3 passa; sem contexto de tenant a consulta devolve zero linha;
    papel da aplicação não enxerga o outro tenant; auditoria recusa `UPDATE`
  - Arquivos: `deploy/migrations/0001_tenancy.sql`, `tests/db/test_esquema.py`
  - ⚠ **É a tarefa mais provável de estourar a sessão**: nove tabelas, índices, RLS com
    `FORCE`, grants de auditoria, colunas do contador e quatro testes. Se estourar, dividir
    em **T6a esquema** (tabelas, índices, grants) e **T6b RLS** (políticas, `FORCE`, papel
    sem `BYPASSRLS`), e avisar — não empurrar um diff que não se revisa de uma sentada.

- [ ] **T7** — Repositório e contexto de tenant
  - Toda consulta a tabela com `tenant_id` passa por um repositório que recebe o
    `Principal` e injeta o filtro; a transação faz `SET LOCAL vzdr.tenant_id`.
  - Testes: conexão reusada do pool para dois tenants não vaza (o risco nº 1 do plano);
    consulta sem contexto devolve zero linha; `SET` em vez de `SET LOCAL` é pego
  - Arquivos: `packages/core-tenancy/src/vzdr/core/tenancy/repositorio.py`,
    `tests/db/test_isolamento.py`

- [ ] **T8** — Auditoria (`vzdr.core.audit`)
  - Pacote novo, dono de `auditoria` e `auditoria_plataforma`. `registrar()` e
    `registrar_plataforma()`, nada mais — **P12**.
  - Vem antes de quem a usa: concessão de papel, bootstrap e tentativa negada escrevem nela.
  - Testes: ato de tenant não cai na tabela de plataforma e vice-versa; principal de serviço
    grava serviço **e** usuário dono (**P6**, **P8**)
  - Arquivos: `packages/core-audit/`, `tests/db/test_auditoria.py`

- [ ] **T9** — Hash de senha
  - `hashlib.scrypt` com `N=2^16, r=8, p=2` (OWASP), `maxmem` **calculado e explícito** —
    o padrão de 32 MiB do OpenSSL recusa estes parâmetros.
  - `senha_params` guarda **algoritmo + parâmetros + salt**. Quem valida lê o algoritmo que
    a linha declara, nunca assume a política atual, e re-hasha no login bem-sucedido quando
    a linha está defasada.
  - Semáforo limitando quantos hashes rodam ao mesmo tempo: 64 MiB por hash é superfície de
    negação de serviço.
  - Testes: hash com parâmetros antigos ainda valida e é re-hasheado no login; algoritmo
    desconhecido falha em vez de cair no padrão; `maxmem` insuficiente é detectado por
    teste, não em produção; senha errada não re-hasha
  - Arquivos: `packages/core-tenancy/src/vzdr/core/tenancy/senha.py`,
    `tests/unit/test_senha.py`

- [ ] **T10** — `autenticar()`, sessão e verificador de token
  - Token opaco (`secrets.token_urlsafe(32)`), banco guarda o SHA-256. `VerificadorDeToken`
    como `Protocol`, `VerificadorLocal` como único implementador.
  - Verificação do token e resolução do papel na **mesma** consulta; `Principal` resolvido
    uma vez por requisição.
  - Testes: token inválido e expirado falham distintos; usuário sem associação ao tenant
    pedido falha; papel vem de `associacao_tenant` e não da sessão; uma consulta por
    autenticação (contada, não estimada)
  - Arquivos: `packages/core-tenancy/src/vzdr/core/tenancy/autenticacao.py`,
    `tests/db/test_autenticacao.py`

- [ ] **T11** — `trocar_tenant()`: a cadeia de sessões
  - Emite sessão para outro tenant a partir de uma sessão válida, sem senha. As três
    decisões de desenho estão na spec, seção "Trocar de tenant: a cadeia de sessões":
    expiração herdada por chave composta, forma em cadeia, e verificação no contexto do
    destino.
  - **Migração `0003`**: `unique (id, expira_em)` em `sessao` e troca do
    `sessao_pai_id` simples pela chave composta
    `(sessao_pai_id, expira_em) → sessao (id, expira_em)`, `on delete cascade`
    `on update cascade`. É ela que torna a herança de expiração garantida e não
    convencionada — verificado em protótipo: o banco recusa expiração diferente.
  - O token da filha leva o prefixo do tenant de **destino** (T10).
  - Audita `tenancy.tenant_trocado` no tenant de destino, com a origem no detalhe.
  - Testes: sem associação no destino falha; expiração diferente é recusada **pelo banco**;
    troca encadeada A→B→C não estende o relógio; revogar qualquer ancestral derruba os
    descendentes, inclusive em outro tenant; token de serviço é recusado; o token da filha
    resolve para o tenant de destino com o papel de lá
  - Arquivos: `deploy/migrations/0003_sessao_encadeada.sql`,
    `packages/core-tenancy/src/vzdr/core/tenancy/sessao.py`,
    `tests/db/test_trocar_tenant.py`

- [ ] **T12** — Papel de plataforma, `sessao_plataforma`, `criar_tenant()` e bootstrap
  - Sessão de plataforma em tabela própria, sem `tenant_id`: um principal de plataforma não
    tem onde carregar tenant, então a invariante deixa de depender de revisão.
  - `criar_tenant(quem, nome, identificador, primeiro_admin)` — o passo 1 do comportamento
    normal da spec, que não tinha dono em nenhuma tarefa. Exige papel de plataforma,
    identificador único, e **cria o tenant e a primeira associação na mesma transação**:
    tenant vazio não é estado do sistema. Auditado nos **dois** lugares —
    `tenancy.tenant_criado` em `auditoria_plataforma` e `tenancy.papel_concedido` na
    auditoria do tenant novo, com o operador como autor. Ver a spec, seção "Criar tenant:
    ele nasce com o primeiro admin".
  - Testes adicionais: tenant nunca existe sem associação; a concessão inicial aparece na
    auditoria do tenant com o operador como autor; `conceder_papel` continua recusando
    principal de plataforma (uma regra só).
  - Bootstrap cria o primeiro papel de plataforma e registra em `auditoria_plataforma`
    como `tenancy.plataforma_iniciada` — evento próprio, porque é o único ato sem autor
    autenticado. Vem junto de `criar_tenant()` porque bootstrap sem tenant nenhum não tem
    o que fazer depois. **Não é endpoint**, roda local com credencial de dono do banco, e
    nunca por agente de IA (**P6**). Recusa rodar se já existir qualquer papel de
    plataforma — condição sobre o estado atual, não sobre o histórico. Senha por variável
    de ambiente exigida, sem padrão. Ver a spec, seção "O primeiro operador de plataforma".
  - O script novo é `scripts/criar-operador-plataforma.py`. **Não** reusar
    `scripts/bootstrap.sh`, que já existe e prepara o ambiente de desenvolvimento.
  - `autenticar_plataforma()` e `verificar_plataforma()` entram aqui. Não estavam nesta
    lista e foram acrescentados na implementação: sem eles o operador não age e
    `sessao_plataforma` fica tabela sem uso. Token opaco inteiro — `sessao_plataforma` não
    tem `tenant_id` nem RLS, e portanto não precisa do prefixo que a sessão de tenant
    precisa. Ficam registrados aqui para o contrato não divergir da implementação no
    sentido oposto ao que motivou a **TI3**.
  - Testes: principal de plataforma é negado em toda ação de tenant, na borda e no SQL;
    sessão de plataforma não vira sessão de tenant; `criar_tenant` sem papel de plataforma
    é negado e auditado; identificador repetido falha; bootstrap é auditado e não repete
  - Arquivos: `packages/core-tenancy/src/vzdr/core/tenancy/plataforma.py`,
    `scripts/criar-operador-plataforma.py`, `tests/db/test_plataforma.py`

- [ ] **T13** — `conceder_papel()` e os dois eventos
  - Um lugar só decide entre `tenancy.papel_concedido` e `tenancy.papel_autoconcedido`,
    comparando concedente e beneficiário — não cada chamador.
  - Nomes conforme ADR-0005; hoje são tipo de linha na auditoria, e `core-006` os publica
    depois sem renomear.
  - Testes: conceder a outro emite `papel_concedido`; conceder a si mesmo emite
    `papel_autoconcedido` e **nunca os dois**; auto-concessão é consultável sem varrer o
    log; conceder sem permissão é negado e auditado
  - Arquivos: `packages/core-tenancy/src/vzdr/core/tenancy/papeis.py`,
    `tests/db/test_conceder_papel.py`

- [ ] **T14** — Token de serviço
  - Modelo e resolução apenas; criar, listar, revogar e rotacionar são `core-007`.
  - O token guarda o dono, **nunca o papel**: o papel vive só em `associacao_tenant`, e é
    isso que faz o rebaixamento propagar sem revogação.
  - **Mesmo formato da sessão**, `<tenant_id>.<segredo>`: `token_servico` tem RLS e o ovo
    e a galinha é idêntico. Formato único, um analisador só.
  - **Migração `0006`**: `ultimo_uso_em timestamptz`. `id` e `descricao` já existem — são o
    identificador visível e o rótulo legível que a tela de `core-007` vai precisar. Gravar
    o uso é **condicional**, com granularidade de minutos, e na mesma instrução da
    resolução: gravar a cada resolução tornaria o caminho de leitura mais quente do sistema
    um caminho de escrita.
  - Testes: token resolve para tenant e papel do dono; **rebaixar o dono muda o papel do
    mesmo token, e uma ação que exigia `admin` passa a ser negada** — é o caso que a chave
    composta *não* cobre, porque a associação continua existindo; dono sem associação
    derruba o token (já coberto pelo esquema); auditoria mostra serviço e dono; token de
    serviço nunca excede o dono; `ultimo_uso_em` é atualizado e não a cada resolução
  - Arquivos: `deploy/migrations/0006_token_servico_uso.sql`,
    `packages/core-tenancy/src/vzdr/core/tenancy/servico.py`,
    `tests/db/test_token_servico.py`

## Ordem

```
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11
                                              T10 → T12
                                              T10 → T13 → T14
```

Dependências que importam, além da sequência:

- **T3 antes de T6**: a primeira migração nasce sob o checador, não o contrário.
- **T5 antes de T6**: o ADR decide o que a migração implementa.
- **T8 antes de T12, T13**: bootstrap e concessão escrevem na auditoria.
- **T4 e T9 não tocam banco**: podem sair de ordem se alguém precisar paralelizar.
- **TI1 depois de T5, antes de T6**: a T6 é a primeira tarefa que traz pacote novo com
  código, e é quando a duplicação passa a custar.

T1 a T3 são infraestrutura; se você quiser valor visível antes, T4 entrega a matriz de
permissão testável sem banco nenhum, mas a primeira migração fica sem rede de proteção.

## Fora desta lista

| O quê | Onde |
| --- | --- |
| HTTP, 401/403, RBAC na borda, auditoria imutável e consultável | `core-007` |
| Ciclo de vida do token de serviço: criar, listar, revogar, rotacionar | `core-007` |
| Limite de tentativa de senha por IP ou origem | `core-007` |
| Aprovação por segunda pessoa para concessão de papel | `core-007` |
| Publicação dos eventos no barramento e webhooks | `core-006` |
| Cache da resolução de papel | Só com p95 medido, e com ADR próprio |
| Validador OIDC | Fronteira pronta em T10; implementação, não |
| Convite de usuário, hierarquia de organizações, SSO | Fora da spec |
