# core-002 — Tarefas

Cada tarefa cabe numa sessão de contexto e vira um commit.

Antes de cada uma: ler `spec.md`. Depois: `make check`, e `make test-db` quando tocar
banco. Teste junto com a implementação, nunca depois — inclusive o caminho de falha.

- [ ] **T1** — ADR-0014: cofre com envelope e KEK fora do banco
  - Decisão, alternativas (cofre externo desde a v1; cifrar direto com uma chave só) e os
    custos reais: mais uma dependência para subir o laboratório, e perder a KEK é perder
    as credenciais.
  - Precede o código porque é ele que decide o que a migração implementa.
  - Arquivos: `docs/adr/0014-cofre-com-envelope.md`

- [ ] **T2** — Migração `0007`: `conexao`, `cofre`, `capacidade_observada`
  - As três com `tenant_id` e RLS, como toda tabela de dado de tenant. Nenhuma exceção
    nova à lista fechada.
  - `cofre` separada de `conexao` para que listar conexões nunca toque o segredo.
  - `kek_id` por linha: sem ele, rotação interrompida deixa linha sem dono.
  - Testes: checador de `tenant_id` passa; RLS habilitada e forçada nas três; listar
    conexões não lê a tabela do cofre
  - Arquivos: `deploy/migrations/0007_conexoes.sql`, `tests/db/test_esquema_conexoes.py`

- [ ] **T3** — Cofre: guardar, abrir, reembrulhar
  - AES-GCM com DEK por credencial; KEK de `VZDR_KEK`, sem padrão — ausente, o processo
    recusa subir dizendo o que falta.
  - `reembrulhar` toca só as DEKs, é retomável e convive com duas KEKs pelo `kek_id`.
  - **Não existe função que devolva segredo para fora do processo.** É assim que "o campo
    é de escrita" deixa de depender de alguém lembrar.
  - Testes: ida e volta; KEK errada não abre; rotação mantém tudo utilizável sem reescrever
    credencial; rotação interrompida é retomável; KEK ausente recusa subir
  - Arquivos: `packages/core-connections/src/vzdr/core/connections/cofre.py`,
    `tests/unit/test_cofre.py`, `tests/db/test_rotacao_de_kek.py`

- [ ] **T4** — O teste de vazamento
  - Tarefa própria de propósito: é a garantia mais fácil de escrever errado e a mais cara
    de errar.
  - Cadastra conexão com segredo reconhecível, provoca falha de autenticação real contra
    o conector fictício, e captura **log, exceção, `traceback` formatado e as duas tabelas
    de auditoria**. Afirma que o segredo não aparece em nenhum dos quatro.
  - Testes: o de cima, mais um que **prova que o teste detecta** — vazar o segredo de
    propósito e ver reprovar
  - Arquivos: `tests/unit/test_credencial_nao_vaza.py`

- [ ] **T5** — Registro e protocolo de conector
  - `Conector` como `Protocol`, `registrar_conector`, `resolver(conexao, capacidade)`.
  - Capacidade inexistente falha **na resolução**, nunca no uso.
  - Testes: conector fictício entra **sem tocar no núcleo** — é o critério de aceite que
    prova a fronteira; capacidade inexistente falha cedo; erro do sistema externo chega
    cru (P8)
  - Arquivos: `packages/core-connections/src/vzdr/core/connections/registro.py`,
    `.../connectors/__init__.py`, `tests/unit/test_registro.py`

- [ ] **T6** — Conector `vhi`: tradução de protocolo
  - Schema de configuração, autenticação no Keystone, mapeamento de erro. Sem cluster:
    respostas gravadas, com cabeçalho de data e origem.
  - Gravação sem cabeçalho **falha o teste**: gravação anônima é gravação que ninguém sabe
    se envelheceu.
  - Testes: forma da requisição; erro cru preservado; gravação sem cabeçalho reprova
  - Arquivos: `packages/core-connections/src/vzdr/core/connections/connectors/vhi/`,
    `tests/gravacoes/vhi/`, `tests/unit/test_conector_vhi.py`

- [ ] **T7** — Health check sob demanda, capacidades e versões
  - Verifica no cadastro, antes de operação cara, e revalidando na falha. **Não** antes de
    cada chamada.
  - Checa **capacidades** e registra **versões**: capacidade é o fato, versão é o proxy.
    Versão nova com capacidades intactas avisa; capacidade de que o produto depende
    sumindo **bloqueia**, nomeando qual sumiu.
  - Emite os eventos — e é aqui que a tabela `Eventos` entra na spec, não antes:
    `connections.conexao_verificada`, `connections.verificacao_falhou`,
    `connections.capacidade_sumiu`. O `check_eventos` exige emissor e teste, então
    declarar antes reprovaria o build.
  - Testes: os três momentos; versão nova não bloqueia; capacidade que some bloqueia com o
    nome; evento em cada caso
  - Arquivos: `.../connections/saude.py`, `tests/db/test_saude.py`

- [ ] **T8** — Integração contra o laboratório
  - O conector `vhi` contra o cluster real. É quem detecta que uma gravação envelheceu.
  - `make gravar-vhi` regenera as gravações a partir do laboratório.
  - **Nunca contra produção** — vale a mesma guarda de host das outras suítes.
  - Testes: `tests/integration`, marcados, fora do `make check`
  - Arquivos: `tests/integration/test_vhi.py`, `Makefile`

## Ordem

```
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8
```

- **T1 antes de T2**: o ADR decide o que a migração implementa — mesma razão de T5 antes
  de T6 na `core-001`.
- **T3 antes de T4**: não dá para testar que o segredo não vaza antes de haver segredo.
- **T5 antes de T6**: o conector `vhi` implementa um protocolo que precisa existir, e o
  fictício da T5 é quem prova que o protocolo basta.
- **T7 declara os eventos**, porque o `check_eventos` exige emissor e teste. Contrato
  publicado é contrato que alguém já pode consumir.

## Fora desta lista

| O quê | Onde |
| --- | --- |
| Health check periódico, e o intervalo padrão | `core-003` — traz o agendador |
| Rotação automática de credencial no OpenStack do cliente | Fora do produto: é o cliente quem rotaciona |
| KMS ou Vault guardando a KEK | v2; o envelope já aceita a troca sem mexer no esquema |
| Descoberta de recursos | `core-005`, inventário |
| Conectores além do `vhi` | Quando houver o segundo sistema externo |
| Versões de libvirt e QEMU | `core-004` — é o agente que as vê |
