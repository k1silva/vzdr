# core-001 — Tenancy e identidade

**Status:** aprovada
**Marco:** M0
**Depende de:** —

## Problema

Toda capacidade da plataforma precisa saber quem está pedindo e em nome de qual
organização. Sem isso, nenhuma outra spec pode começar sem chutar o modelo.

## Resultado esperado

Toda requisição resolve para um **principal**: uma identidade com tenant e papel, sobre a
qual a autorização decide. Toda entidade pertence a um tenant. A plataforma nasce com um
tenant só, mas o modelo já suporta vários — inclusive um usuário que existe em mais de um.

## Modelo

### Principal

O que a autenticação produz e o que a autorização consome. Nada além disso atravessa a
fronteira da API.

| Campo | O quê |
| --- | --- |
| `origem` | `usuario` ou `servico` |
| `usuario_id` | sempre preenchido — no token de serviço, é o usuário dono |
| `servico_id` | só quando `origem = servico` |
| `tenant_id` | tenant ativo; ausente no papel de plataforma |
| `papel` | papel resolvido para esse tenant, ou o papel de plataforma |

### Autenticação — token próprio, emissor plugável

O token é emitido e assinado pela plataforma. Senha, expiração e rotação de chave são
responsabilidade do núcleo.

A API não valida token diretamente: chama `verificar_token(token) -> Principal`. Hoje há um
único implementador, o validador local. Um validador OIDC entra depois como outro
implementador, sem tocar em quem consome o principal.

Não depender de IdP externo mantém M0 e a CI de pé com `make db-up` e nada mais.

**O token de sessão de tenant é `<tenant_id>.<segredo>`.** A spec dizia apenas "token
próprio"; o prefixo apareceu ao implementar. `sessao` tem `tenant_id`, logo tem RLS, e ler
a linha exige o contexto de tenant — que só se saberia lendo a linha. As alternativas eram
piores: dar ao verificador uma conexão sem RLS, tirar a RLS de `sessao`, ou criar uma
função `security definer` que a contorna. Todas trocam um problema de bootstrap por uma
superfície privilegiada nova.

Trocar o prefixo não abre nada: o hash guardado é do token inteiro, então prefixo
diferente dá hash diferente — e a RLS do tenant trocado esconderia a linha de qualquer
forma. O que o prefixo revela é o tenant de quem já tem o token.

Sessão de plataforma não tem esse problema: `sessao_plataforma` não tem `tenant_id` nem
RLS, e o token dela é opaco inteiro.

### Papel é por tenant

A associação `(usuario, tenant, papel)` é uma tabela própria, não uma coluna em `usuario`.
Um usuário pode ser `admin` no tenant A e `viewer` no B. O token carrega o tenant ativo; o
papel é resolvido na autenticação para aquele tenant.

A fronteira de permissão e a fronteira de dados têm que ser a mesma. Com papel global, o
teste de isolamento entre tenants não teria como existir: faltaria o usuário que pertence
aos dois.

### Senha: o algoritmo mora na linha, e a migração acontece no login

`senha_params` guarda algoritmo, parâmetros e salt, nessa ordem. Quem valida lê o
algoritmo que a linha declara e **nunca** assume a política vigente.

Isso sozinho não migra nada. **Login bem-sucedido cuja linha está defasada re-hasheia na
hora** — é o único momento em que a senha em claro existe. Sem essa regra, "adotar outro
algoritmo depois é aditivo" é plano que nunca executa: os parâmetros ficam gravados,
ninguém migra, e daqui a dois anos o parque inteiro continua no original. Vale igual para
subir o custo sem trocar de algoritmo, que é o caso mais provável.

### Token de serviço

O modelo entra aqui; o ciclo de vida (criar, listar, revogar, rotacionar) é `core-007`.

Todo token de serviço tem um usuário dono e resolve para um principal com **o mesmo tenant
e o mesmo papel do dono** — nunca mais que isso. O papel é resolvido na autenticação, não
congelado na emissão: se o dono perde o papel, o token perde junto, no uso seguinte.

É assim que a CLI e o assistente de IA agem sem privilégio próprio. O assistente herda a
autoridade de quem o acionou, e ação destrutiva continua exigindo confirmação humana (P6).

### Trocar de tenant: a cadeia de sessões

Um usuário com papel em dois tenants troca de um para o outro **sem digitar a senha de
novo** — é a consequência direta de papel ser por tenant, e sem isso o caso de teste
central da spec seria hostil de usar.

**A expiração é herdada, e o banco garante isso.** A sessão nova tem `expira_em` **igual**
ao da que a originou, imposto por chave estrangeira composta
`(sessao_pai_id, expira_em) → sessao (id, expira_em)`. Não é convenção: o banco recusa
`insert` com expiração diferente. Sem essa garantia, trocar de tenant em sequência
renovaria o relógio a cada salto e a sessão duraria para sempre.

**A forma é cadeia, não leque.** Trocar de A para B e depois de B para C cria uma sessão
filha **de B**, não uma irmã de B sob A. As duas formas pareceriam equivalentes e não são:
no leque, revogar B deixaria C viva, e C nasceu de B — quem tivesse o token de B levaria C
consigo depois da revogação. Na cadeia, revogar qualquer ancestral derruba tudo que desceu
dela, porque o `on delete cascade` é recursivo.

"Sessão irmã" descreve o propósito — mesmo login, outro tenant —, não o formato dos dados.
Quem revoga precisa saber o que cai junto: **cai tudo que foi derivado**, direta ou
indiretamente.

A chave composta também trava o `expira_em` da mãe: qualquer `update` nele violaria a
referência das filhas. Por isso `on update cascade`, e não por simetria — **esta spec não
descarta renovação de sessão**, e no dia em que alguém implementar expiração deslizante o
comportamento certo é renovar a cadeia junto. Sem a cláusula, essa pessoa encontraria um
`ForeignKeyViolation` que não explica nada e "consertaria" a restrição.

#### O tamanho da cadeia

Trocar de tenant **sempre cria um nível**; não há reuso de sessão existente. E não há por
uma razão técnica, não por escolha: o banco guarda só o SHA-256 do token, então "reusar"
não poderia devolver o token de volta — ele não é recuperável. Alternar entre dois tenants
cinquenta vezes cria cinquenta linhas, e voltar a A deixa a segunda sessão de A como neta
da primeira, no mesmo tenant.

Isso é inofensivo por três motivos, e vale dizer quais são para o dia em que parecer que
não é:

1. o crescimento é limitado pela vida da raiz — toda a cadeia morre com o login, e a raiz
   dura 12 horas;
2. **nenhuma consulta percorre a cadeia.** `sessao_pai_id` não aparece em nenhuma consulta
   deste repositório: quem o segue é o `on delete cascade` do PostgreSQL, iterativo e do
   lado do banco;
3. a linha é pequena e o índice é por `token_hash`, não por profundidade.

Se algum dia a profundidade incomodar, o limite é uma coluna de profundidade com `check`,
não um percurso. Enquanto não houver medição de que incomoda, não existe.

**A verificação do destino usa o próprio destino.** Conferir se o usuário tem papel em B
exige ler `associacao_tenant`, que tem RLS — e no contexto de A a linha de B está
escondida. A saída é que o destino é conhecido: o usuário pediu para ir a B. Abre-se o
contexto em B e procura-se `(usuario, B)`. Existe, e a RLS deixa ver; não existe, e vêm
zero linhas — que é exatamente "não é membro". Sem conexão privilegiada e sem
`security definer`, a mesma disciplina do token de sessão.

A linha filha vive no tenant de destino e aponta para uma mãe no tenant de origem. Isso
atravessa a fronteira de tenant de propósito, e funciona porque **verificação de
integridade referencial ignora RLS** no PostgreSQL — é o que faz o cascade alcançar
descendentes em outros tenants. Verificado, não suposto.

**O que esse fato custa.** Se a integridade referencial ignora RLS, a chave estrangeira é
um oráculo de existência entre tenants: um `insert` que passa prova que existe sessão com
aquele par `(id, expira_em)` em **algum** tenant, mesmo que o autor não possa vê-la.

Na prática é inexplorável — exige acertar um UUID v4 e o instante exato junto, e o retorno
é um bit. Fica escrito pelo mesmo motivo que o prefixo do token: é consequência real do
desenho, e quem for mexer nisto depois precisa saber que existe, em vez de descobrir.

Token de serviço **não** troca de tenant: é emitido para um e nele fica. Automação que
atende dois tenants tem dois tokens, e isso é desejável — a auditoria diz qual agiu.

#### O que isto não resolve: listar os tenants de um usuário

Trocar de tenant funciona porque o destino é conhecido. **"Quais são os meus tenants?" não
tem destino conhecido**, e é a primeira pergunta que a tela de troca faz. Sob RLS, a
resposta exigiria abrir um contexto por tenant candidato — o que pressupõe já saber a
lista.

Está fora desta spec, mas fica escrito para ninguém improvisar quando a tela aparecer. As
saídas plausíveis, em ordem de preferência:

1. o login resolver a lista e o token carregá-la, porque no login o contexto ainda não
   existe e a consulta pode acontecer antes de qualquer `set_config`;
2. uma tabela de índice `usuario → tenants` fora do eixo de tenant — o que significa mais
   uma linha na lista fechada de exceções, e portanto alteração de spec;
3. uma função `security definer` estreita: a saída que esta spec já recusou duas vezes, e
   que só deveria voltar com argumento novo.

### Revogar sessão é apagar a linha

Revogação de sessão é `DELETE`, não marca de estado. A spec não dizia, e a diferença
importa: a garantia "sessão irmã não sobrevive à mãe" é imposta pelo `on delete cascade`
de `sessao_pai_id`. Com marca de estado — `revogada_em`, `status` — a cascata nunca
dispara, e a invariante volta a depender de alguém lembrar de propagar.

O que precisa sobreviver ao ato é o registro na auditoria, que é outra tabela. Reter
sessão revogada é retenção de auditoria, não de `sessao`.

Trocar isto por *soft delete* exige outro mecanismo para a mesma garantia — gatilho ou
propagação explícita — e é alteração de spec, não detalhe de implementação.

### Papel de plataforma

Existe fora do eixo de tenant. Não é um tenant especial e não é superusuário.

| Pode | Não pode |
| --- | --- |
| Criar e gerir tenants | Ler dado de tenant |
| Criar usuários e conceder papéis | Escrever dado de tenant |
| Ver saúde da infraestrutura | Ver saúde da proteção de um tenant |
| | Conceder papel a si mesmo sem que o ato apareça na auditoria |

Para ler dado de um tenant, alguém concede a ele um papel dentro daquele tenant. A
concessão é um ato auditado, e é o que torna o acesso visível em vez de implícito.

Nada impede o papel de plataforma de conceder um papel a si mesmo — impedir seria teatro,
já que ele pode criar um segundo operador e os dois se concederem mutuamente. O que a
auditoria faz é **não deixar isso passar como concessão comum**: quando quem concede e quem
recebe são o mesmo principal, o evento é `tenancy.papel_autoconcedido`, não
`tenancy.papel_concedido`. Ter um tipo próprio é o que permite alertar sobre ele sem varrer
o log inteiro.

Os nomes seguem a convenção `dominio.acao`, no passado e em snake_case — ver
`docs/adr/0005-convencao-de-eventos.md`.

### Saúde são duas coisas, em eixos diferentes

Não existe uma ação "ver saúde". Existem duas, e confundi-las vaza tenant.

| Ação | Eixo | O que mostra |
| --- | --- | --- |
| `ver_saude_tenant` | Tenant | A proteção **daquele** tenant: RPO sendo cumprido, último ciclo, último ponto de recuperação, VMs protegidas |
| `ver_saude_plataforma` | Plataforma | A infraestrutura: relés, pool de receptoras, filas, agentes, todos os tenants somados |

A primeira é produto, não extra: o cliente precisa saber se a proteção dele está de pé,
e é a resposta que a interface dá na tela inicial. Todo papel de tenant a tem, `viewer`
inclusive — ler o próprio estado é o mínimo de `viewer`.

A segunda o tenant **não** pode, nem o `admin` dele. Ela agrega os tenants e expõe fila,
capacidade e contagem — ou seja, a existência de outros clientes. Um cliente descobrir
quantos outros existem, ou que a fila está cheia por causa deles, é vazamento de tenant
mesmo sem nenhuma linha de dado alheio aparecer.

O papel de plataforma tem a segunda e **não** tem a primeira: para ver a proteção de um
tenant, ele precisa de um papel concedido dentro daquele tenant, como qualquer leitura de
dado de tenant.

### O que fica fora do eixo de tenant

Decidir papel por tenant tem uma consequência no esquema: o usuário passa a existir
independente de tenant, porque o vínculo vive na associação. Logo `usuarios` é uma tabela
**sem** `tenant_id`. A lista de exceções é fechada — nada entra nela sem alterar esta spec.

| Tabela | Por que não tem `tenant_id` |
| --- | --- |
| `tenants` | É o próprio eixo |
| `usuarios` | O vínculo vive em `associacao_tenant`, que pode ter mais de uma linha por usuário |
| `papel_plataforma` | Existe fora do eixo por definição; um papel de plataforma com tenant seria um tenant privilegiado |
| `auditoria_plataforma` | Registra atos que não acontecem dentro de tenant nenhum: criar tenant, criar usuário, conceder papel |
| `sessao_plataforma` | Sessão do papel de plataforma, que não tem tenant ativo; separá-la de `sessao` é o que impede um principal de plataforma de portar um tenant |
| `schema_migrations` | Metadado do executor de migração. Única da lista que **não** é criada por um arquivo de migração: quem a cria é `scripts/migrar.py`, antes de saber o que já foi aplicado |

`associacao_tenant` **tem** `tenant_id`: é ela que carrega o vínculo, e é por ela que toda
resolução de papel passa.

A auditoria de ação dentro de um tenant é outra tabela, com `tenant_id`, e não se mistura
com `auditoria_plataforma`. Separar as duas é o que impede um ato de plataforma de aparecer
como se tivesse acontecido dentro de um tenant.

`tests/invariants/check_tenant_id.py` espelha esta tabela, com a justificativa de cada
exceção no código, e um teste falha se as duas listas divergirem. É o que dá força à regra:
acrescentar exceção só no checador não passa na CI.

## Papéis dentro do tenant

| Papel | Pode |
| --- | --- |
| `viewer` | Ler tudo do seu tenant, incluindo a saúde da proteção dele |
| `operator` | Configurar proteção, rodar test-failover |
| `admin` | Tudo do operator, mais disparar failover e gerir usuários |

Disparar failover é separado de operar porque é destrutivo e decide negócio.

## Comportamento normal

1. Um tenant é criado com nome e identificador, pelo papel de plataforma.
2. Um usuário é criado e associado a um tenant com um papel.
3. O usuário autentica; o token carrega o tenant ativo e o papel resolvido para ele.
4. Um token de serviço é emitido por um usuário dono e resolve para o tenant e o papel dele.
5. Toda consulta e toda escrita é filtrada pelo tenant do principal.
6. Toda ação verifica se o papel permite, antes de executar.
7. Toda ação auditada registra o usuário. Quando veio de token de serviço, registra o
   serviço **e** o usuário dono.
8. Conceder papel emite `tenancy.papel_concedido`; conceder papel a si mesmo emite
   `tenancy.papel_autoconcedido`, nunca os dois.

## Comportamento em falha

| Falha | O que acontece | Estado resultante |
| --- | --- | --- |
| Token inválido ou malformado | 401, nada executa | Inalterado |
| Token expirado | 401, nada executa — **erro distinto do inválido**, porque a interface diz "entre de novo", não "token errado" | Inalterado |
| Papel insuficiente | 403, registra tentativa na auditoria | Inalterado |
| Usuário sem associação ao tenant pedido | 403, registra tentativa na auditoria | Inalterado |
| Papel de plataforma pede dado de tenant | 403, registra tentativa na auditoria | Inalterado |
| Dono do token de serviço perdeu o papel | 403 no uso seguinte, sem revogação necessária | Inalterado |
| Token de serviço sem usuário dono resolvível | 401, nada executa | Inalterado |
| Consulta sem filtro de tenant | Falha em teste, build quebra | Não chega em produção |

## Invariantes

- **P9:** toda tabela que guarda dado de tenant tem `tenant_id`, desde a primeira migração.
  A lista de exceções é fechada, justificada e vive nesta spec; acrescentar uma exceção é
  alterar a spec, não editar o checador. Escrita como "toda tabela, sem exceção", a
  invariante seria falsa no próprio desenho que esta spec propõe — e invariante falsa é pior
  que invariante ausente, porque o checador vira ruído que alguém aprende a silenciar.
- **P9:** o papel de plataforma não lê nem escreve dado de tenant nenhum. Nenhum principal
  atravessa a fronteira de tenant sem uma concessão explícita de papel dentro daquele
  tenant, e a concessão é auditada. Um papel que enxerga tudo transforma o isolamento em
  teatro e esvazia os testes de tenancy.
- **P6:** ação destrutiva exige papel `admin` e confirmação explícita, inclusive quando o
  pedido chega por token de serviço.
- **P6, P8:** a auditoria de ação vinda de token de serviço registra o serviço e o usuário
  dono. Registrar só o serviço apaga de quem a autoridade foi emprestada.
- **P6:** auto-concessão de papel é um tipo de evento próprio na auditoria
  (`tenancy.papel_autoconcedido`), nunca um `tenancy.papel_concedido` genérico. Confundir os
  dois esconde a única concessão que ninguém revisou dentro do volume das que alguém revisou.
- **P7:** autenticação e autorização acontecem na API, não na interface.
- Um token de serviço nunca tem tenant ou papel diferente do usuário dono.

## Critério de aceite

- [ ] Uma consulta sem filtro de tenant falha num teste automatizado
- [ ] Usuário associado a dois tenants enxerga cada um só com o papel daquele tenant
- [ ] Usuário de um tenant não enxerga dados de outro, com teste
- [ ] Papel de plataforma recebe 403 ao pedir dado de tenant, com teste
- [ ] Papel de plataforma concedido dentro de um tenant passa a enxergar, e a concessão
      aparece na auditoria como `tenancy.papel_concedido`
- [ ] Conceder papel a si mesmo aparece na auditoria como `tenancy.papel_autoconcedido`,
      distinguível por consulta sem ler o resto do log
- [ ] Nenhuma tabela nova sem `tenant_id` fora da lista de exceções desta spec, com checador
- [ ] Login com senha defasada re-hasheia na hora, e a senha continua valendo
- [ ] Autenticar usuário inexistente executa o mesmo trabalho de hash que um existente
- [ ] Cada papel tem teste de permissão concedida e negada
- [ ] Token de serviço tem o papel do dono; rebaixar o dono rebaixa o token, com teste
- [ ] Ação por token de serviço aparece na auditoria com serviço e usuário dono
- [ ] Tentativa negada aparece na auditoria

## Fora de escopo

Convite de usuário, hierarquia de organizações, SSO e federação — o validador OIDC é
previsto pela fronteira de `verificar_token`, não implementado aqui.

Ciclo de vida de token de serviço (criar, listar, revogar, rotacionar): `core-007`.

Limite de tentativa de senha **por IP ou origem**: `core-007`, onde o HTTP existe. O
contador e o bloqueio por usuário são dado e ficam aqui, junto de `usuarios`. A distinção
importa: com hash memory-hard, login sem limite é negação de serviço barata, e o controle
que falta não pode ficar sem dono entre as duas specs.

Aprovação por segunda pessoa para concessão de papel: `core-007`. Separação de funções de
verdade exige um segundo aprovador, o que só significa alguma coisa quando houver mais de um
operador de plataforma. Até lá, a auditoria com tipo de evento próprio é o controle.
