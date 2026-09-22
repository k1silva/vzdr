# core-001 — Tenancy e identidade

**Status:** rascunho
**Marco:** M0
**Depende de:** —

## Problema

Toda capacidade da plataforma precisa saber quem está pedindo e em nome de qual
organização. Sem isso, nenhuma outra spec pode começar sem chutar o modelo.

## Resultado esperado

Existe um usuário autenticado, pertencente a um tenant, com um papel que determina o que
pode fazer. Toda entidade pertence a um tenant. A plataforma nasce com um tenant só, mas o
modelo já suporta vários.

## Comportamento normal

1. Um tenant é criado com nome e identificador.
2. Um usuário é criado dentro de um tenant, com um papel.
3. O usuário autentica e recebe um token com tenant e papel.
4. Toda consulta e toda escrita é filtrada pelo tenant do token.
5. Toda ação verifica se o papel permite, antes de executar.

## Papéis iniciais

| Papel | Pode |
| --- | --- |
| `viewer` | Ler tudo do seu tenant |
| `operator` | Configurar proteção, rodar test-failover |
| `admin` | Tudo do operator, mais disparar failover e gerir usuários |

Disparar failover é separado de operar porque é destrutivo e decide negócio.

## Comportamento em falha

| Falha | O que acontece | Estado resultante |
| --- | --- | --- |
| Token inválido ou expirado | 401, nada executa | Inalterado |
| Papel insuficiente | 403, registra tentativa na auditoria | Inalterado |
| Consulta sem filtro de tenant | Falha em teste, build quebra | Não chega em produção |

## Invariantes

- **P9:** toda tabela tem `tenant_id`, desde a primeira migração.
- **P6:** ação destrutiva exige papel `admin` e confirmação explícita.
- **P7:** autenticação e autorização acontecem na API, não na interface.

## Critério de aceite

- [ ] Uma consulta sem filtro de tenant falha num teste automatizado
- [ ] Usuário de um tenant não enxerga dados de outro, com teste
- [ ] Cada papel tem teste de permissão concedida e negada
- [ ] Tentativa negada aparece na auditoria

## Fora de escopo

Convite de usuário, hierarquia de organizações, SSO e federação.

## Perguntas em aberto

- [ ] Token próprio ou OIDC contra um provedor existente?
- [ ] Papel é por tenant ou global?
