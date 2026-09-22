# core-001 — Plano técnico

**Spec:** ./spec.md

## Abordagem

Três camadas, separadas pela pureza:

1. **Domínio puro** (`vzdr.core.domain`): `Principal`, `Papel`, `Acao` e a função de decisão
   `pode(principal, acao)`. Sem IO, sob `mypy --strict` — é o que a constitution exige do
   núcleo de domínio, e é o que permite testar toda a matriz de permissão em `tests/unit`
   sem banco.
2. **Tenancy** (`vzdr.core.tenancy`, pacote novo): tabelas, resolução de papel, emissão e
   verificação de token. Faz IO, conhece o Postgres.
3. **Auditoria** (`vzdr.core.audit`, pacote novo): escreve o que aconteceu. Ver adiante.

Nomes de módulo em inglês, nomes de tabela e termo de negócio em português — a convenção do
AGENTS.md. Sintaxe 3.9: `Optional[X]`, nunca `X | Y`, nunca `match`.

### Token opaco, não JWT

O token é um valor aleatório (`secrets.token_urlsafe(32)`); o banco guarda só o SHA-256
dele. Não é JWT e não carrega claims.

Isso decorre da spec, não é preferência: o papel é **resolvido na autenticação, não
congelado na emissão**. Um token autocontido que dispensa o banco é exatamente a
propriedade que a spec rejeitou — se o papel viaja dentro do token, ele sobrevive à
revogação do acesso do dono. Como toda requisição vai ao banco de qualquer jeito para
resolver o papel, um JWT não economizaria nada e ainda traria uma dependência de
criptografia e um mecanismo de revogação por fora.

O token é aleatório de alta entropia, então o hash de verificação é SHA-256 e não um KDF
lento: não há o que adivinhar. Senha de usuário é outra coisa — ver Dependências.

### Resolução de papel sem virar gargalo

A preocupação é legítima: resolver a cada autenticação significa tocar o banco em toda
requisição. Quatro medidas, em ordem de importância:

**Uma consulta, não três.** A verificação do token e a resolução do papel são a *mesma*
consulta — um join de `sessao` (ou `token_servico`) com `usuarios` e `associacao_tenant`,
todos por índice único: `token_hash`, chave primária, e `(usuario_id, tenant_id)`. Três
buscas em índice numa consulta só, na conexão que a requisição já abriu.

**Uma vez por requisição, nunca por verificação.** O gargalo real não é a autenticação, é
re-resolver o papel a cada `pode(...)`. O `Principal` é resolvido uma vez, na borda, e
viaja como valor imutável pelo resto da requisição. `pode()` é função pura sobre esse
valor: não abre conexão, não consulta nada. Um `pode()` que vá ao banco é bug, e o teste
de invariante pode pegá-lo — `vzdr.core.domain` não importa IO, então ele nem compila.

**O custo comparado é zero.** A alternativa sem consulta (JWT autocontido) foi descartada
por segurança, não por desempenho. Contra qualquer alternativa que preserve a revogação
imediata, uma busca em índice é o piso, não o teto.

**A saída de escala existe, e não se constrói agora.** Se a medição mostrar que o passo de
autenticação pesa, cache em processo por hash de token com TTL de poucos segundos,
invalidado pelo evento `tenancy.papel_concedido` quando `core-006` existir. Isso troca
revogação imediata por janela de obsolescência limitada e explícita — uma decisão de
segurança, que exige ADR próprio. **P12:** o núcleo cresce quando a feature precisa, não
antes. Construir o cache agora seria otimizar sem medida e enfraquecer a propriedade que
acabamos de escolher.

O ponto de medição fica registrado: p95 do passo de autenticação, exposto desde o começo.
Sem número, a discussão de cache vira gosto.

### 401 e 403 são de `core-007`

A spec fala em 401 e 403, mas HTTP mora em `core-007`. Aqui a autenticação devolve
`Principal` ou levanta uma falha tipada (`TokenInvalidoError`, `PapelInsuficienteError`,
`SemAssociacaoNoTenantError`); o mapeamento para status é de `core-007`. Os testes de `core-001`
afirmam a decisão, não o código HTTP. **P7:** a regra vive na API, não na interface — e
também não no controlador.

### Ainda não há barramento de eventos

`core-006` é quem publica. Até lá, `tenancy.papel_concedido` e
`tenancy.papel_autoconcedido` são **tipos de linha na auditoria**, com exatamente o nome que
terão no barramento (ADR-0005). `core-006` passa a publicá-los sem renomear nada.

## Módulos tocados

| Pacote | O que muda |
| --- | --- |
| `packages/core-domain` | Novo: `Principal`, `Origem`, `Papel`, `Acao`, `pode()`. Puro, `mypy --strict` |
| `packages/core-tenancy` | **Pacote novo.** Tabelas, resolução de papel, verificador de token, concessão de papel |
| `packages/core-audit` | **Pacote novo.** `auditoria` e `auditoria_plataforma` |
| `deploy/migrations` | Primeira migração SQL |
| `scripts/` | Executor de migração: aplica `*.sql` em ordem, um por transação |
| `tests/invariants/check_tenant_id.py` | Lista fechada de exceções, com justificativa no código |
| `tests/unit`, `tests/db` | Matriz de permissão (puro) e isolamento entre tenants (com banco) |
| `pyproject.toml` | `mypy_path` dos dois pacotes novos; marcador `db` |
| `Makefile` | Alvo `test-db` |
| `AGENTS.md` | `tests/db` e `make test-db` na estrutura e nos comandos |
| `.github/workflows` | Passo com Postgres de pé para `test-db` |
| `docs/adr/` | ADR-0006 (isolamento por RLS) |

Dois pacotes novos, nenhuma dependência nova além do driver — ver Dependências.

### Onde mora a auditoria de ação de plataforma

A spec decidiu que são duas tabelas. Falta dizer de quem elas são.

Não é de `core-tenancy`: auditoria não é tenancy, e `core-007` ("API e auditoria") teria de
importar de tenancy ou mudar a tabela de dono depois. Não é de `core-api`: auditoria é
escrita por serviço de domínio, não pela camada HTTP, e `core-api` é composição.

Então **pacote próprio, `vzdr.core.audit`**, dono das duas tabelas, com uma interface
estreita:

```python
def registrar(evento: str, principal: Principal, alvo: str,
              detalhe: Optional[Mapping[str, str]] = None) -> None: ...

def registrar_plataforma(evento: str, principal: Principal, alvo: str,
                         detalhe: Optional[Mapping[str, str]] = None) -> None: ...
```

**P10:** se duas features precisariam da mesma coisa, ela é do núcleo — e auditoria está
listada como capacidade do núcleo em `docs/02-plataforma.md`. **P12:** nasce mínima, porque
só `core-001` precisa dela hoje; `core-007` faz crescer (imutabilidade, retenção, consulta,
exposição na API).

Duas funções em vez de um `tenant_id` nulável é deliberado. Coluna nulável faz uma consulta
filtrada por tenant descartar ou incluir linha de plataforma em silêncio, conforme o
`WHERE` — exatamente o buraco que **P9** existe para fechar. Com duas tabelas, o
chamador escolhe, e a escolha errada aparece na revisão.

## Modelo de dados

Uma migração, `deploy/migrations/0001_tenancy.sql`.

| Tabela | `tenant_id` | Notas |
| --- | --- | --- |
| `tenants` | não | O próprio eixo |
| `usuarios` | não | `email` único, `senha_hash`, `senha_params` (algoritmo + parâmetros + salt), contador de falhas e `bloqueado_ate` |
| `associacao_tenant` | **sim** | `(usuario_id, tenant_id)` único, `papel` |
| `papel_plataforma` | não | `usuario_id`; fora do eixo por definição |
| `sessao` | **sim** | `token_hash` único, `usuario_id`, tenant ativo, `expira_em`, `sessao_pai_id` |
| `sessao_plataforma` | não | Papel de plataforma não tem tenant ativo; ver adiante |
| `token_servico` | **sim** | `token_hash` único, `usuario_dono_id`, tenant ativo |
| `auditoria` | **sim** | Ato dentro de um tenant |
| `auditoria_plataforma` | não | Ato que não acontece dentro de tenant nenhum |
| `schema_migrations` | não | Metadado do executor de migração: nome, SHA-256, instante |

A lista sem `tenant_id` é a da spec, sem acréscimo. `sessao` e `token_servico` **têm**
`tenant_id` (o tenant ativo), o que os mantém dentro do eixo e sob a mesma política de
isolamento.

`token_servico` guarda o dono, nunca o papel — **o papel não existe em lugar nenhum além de
`associacao_tenant`**. É assim que rebaixar o dono rebaixa o token sem revogação.

### Isolamento por construção

O critério de aceite exige que consulta sem filtro de tenant *falhe*, não que alguém lembre
do `WHERE`. Três camadas:

1. **Repositório**: toda consulta a tabela com `tenant_id` passa por um repositório que
   recebe o `Principal` e injeta o filtro. SQL solto em serviço não passa na revisão.
2. **RLS no Postgres**: `ENABLE ROW LEVEL SECURITY` + `FORCE` em toda tabela com
   `tenant_id`, política sobre `current_setting('vzdr.tenant_id')`, com `SET LOCAL` dentro da
   transação. Consulta sem contexto devolve zero linha em vez de vazar. É o que torna o
   critério verdadeiro por construção, e vira ADR-0006.
3. **Checador na CI**: o `check_tenant_id.py` ajustado abaixo.

### O ajuste em `check_tenant_id.py`

Hoje o checador tem `ISENTAS = {"alembic_version", "tenants", "schema_migrations"}` — um
conjunto anônimo, onde acrescentar nome é uma linha que ninguém questiona na revisão. Vira
um mapa de tabela para justificativa, espelhando a lista fechada da spec:

```python
# A lista de excecoes e FECHADA e vive em specs/core-001-tenancy/spec.md.
# Acrescentar entrada aqui sem alterar a spec e violacao de P9, nao configuracao.
ISENTAS = {
    "tenants": "e o proprio eixo de tenant",
    "usuarios": "o vinculo com tenant vive em associacao_tenant, que pode ter"
                " mais de uma linha por usuario",
    "papel_plataforma": "existe fora do eixo; papel de plataforma com tenant"
                        " seria um tenant privilegiado",
    "sessao_plataforma": "sessao do papel de plataforma, que nao tem tenant ativo",
    "auditoria_plataforma": "registra atos que nao acontecem dentro de tenant nenhum",
    "schema_migrations": "metadado do executor de migracao",
}
```

Duas mudanças de comportamento, além do texto:

- **Exceção não usada falha o build.** Nome no mapa que nenhuma migração cria é exceção
  morta — some ou alguém a herda sem saber por quê.
- **A mensagem de erro cita a justificativa e o arquivo da spec.** Quem tropeçar às três da
  manhã lê o porquê, não só o quê. É o espírito de **P8** aplicado ao build.

A invariante que o checador imprime também muda: não "tenant_id em toda tabela", e sim
"toda tabela que guarda dado de tenant tem tenant_id; exceções fechadas na spec".

**Decidido: SQL puro com `schema_migrations`.** Alembic existe sobretudo para gerar
migração a partir de modelo de ORM, e não há ORM aqui — traria dependência e cerimônia sem
entregar aquilo que o justifica. A spec foi corrigida: `alembic_version` saiu da lista de
exceções e entrou `schema_migrations`.

### O executor de migração é código nosso

Recusar Alembic não é ganhar migração de graça: é assumir o executor. Ele é tarefa própria,
com teste, não um detalhe da primeira migração.

O contrato é curto e tem que valer sempre:

- aplica `deploy/migrations/*.sql` em ordem lexicográfica de nome;
- **cada arquivo dentro de uma transação** — falha no meio não deixa esquema parcial, e é a
  mesma disciplina que **P4** exige do ciclo de replicação: interromper não corrompe;
- grava nome e instante em `schema_migrations` na mesma transação do arquivo, para não
  existir estado onde o DDL passou e o registro não;
- arquivo já registrado é pulado, então rodar duas vezes é inócuo;
- arquivo que mudou depois de aplicado falha o executor, em vez de aplicar silenciosamente
  outra coisa: guardamos o SHA-256 do conteúdo junto do nome.

Fora do ambiente local ele não roda sozinho: AGENTS.md proíbe migração fora do local, e a
constitution exige confirmação humana para o que é destrutivo (**P6**).

## Interfaces

Domínio puro, `vzdr.core.domain.tenancy`:

```python
class Origem(str, Enum):        # usuario | servico
class Papel(str, Enum):         # viewer | operator | admin
class Acao(str, Enum):          # ler, configurar_protecao, rodar_test_failover,
                                # disparar_failover, gerir_usuarios,
                                # gerir_tenants, ver_saude

@dataclass(frozen=True)
class Principal:
    origem: Origem
    usuario_id: UUID
    servico_id: Optional[UUID]
    tenant_id: Optional[UUID]     # ausente no papel de plataforma
    papel: Optional[Papel]        # ausente no papel de plataforma
    plataforma: bool

def pode(principal: Principal, acao: Acao) -> bool: ...
def e_destrutiva(acao: Acao) -> bool: ...
```

`pode()` é total e pura: a matriz inteira de papel x ação, incluindo o papel de plataforma,
que recebe `False` para tudo que toque dado de tenant. **P9**, segunda invariante da spec.

`vzdr.core.tenancy`:

```python
class VerificadorDeToken(Protocol):
    def verificar(self, token: str) -> Principal: ...

class VerificadorLocal:           # unico implementador hoje
    def verificar(self, token: str) -> Principal: ...

def autenticar(email: str, senha: str, tenant: UUID) -> str: ...
def trocar_tenant(sessao_atual: str, tenant_destino: UUID) -> str: ...
def conceder_papel(quem: Principal, usuario: UUID, tenant: UUID, papel: Papel) -> None: ...
```

`conceder_papel` é quem decide entre `tenancy.papel_concedido` e
`tenancy.papel_autoconcedido`, comparando concedente e beneficiário. A decisão fica num
único lugar, com teste, para não depender de cada chamador lembrar.

O `Protocol` é a fronteira que a spec prometeu: um validador OIDC entra como segundo
implementador sem tocar em quem consome `Principal`.

## Dependências novas

| Dependência | Justificativa |
| --- | --- |
| `psycopg[binary]` (3.x) | É preciso falar com o Postgres. SQL escrito à mão, sem ORM: as migrações já são SQL versionado (`deploy/README.md`) e são oito tabelas. Um ORM traria mapeamento, sessão e lazy loading para resolver um problema que não temos, e é ele que costuma esconder a consulta sem filtro de tenant |

Dependências **evitadas**, e como:

- **Biblioteca de JWT**: desnecessária com token opaco (ver Abordagem).
- **`argon2-cffi` / `bcrypt`**: `hashlib.scrypt` é stdlib desde 3.6. Ver "Hash de senha"
  abaixo — com o algoritmo gravado junto do hash, adotar Argon2id depois é aditivo, não
  reset em massa.
- **Alembic**: ver a pendência acima.
- **FastAPI**: é de `core-007`.

## Hash de senha

`hashlib.scrypt`, stdlib, zero dependência. E a decisão **não é irreversível**, ao contrário
do que a primeira versão deste plano afirmou: o campo guarda o **algoritmo**, não só os
parâmetros.

```
senha_params = "scrypt$ln=16,r=8,p=2$<salt em base64>"
                ^^^^^^ algoritmo
```

Com o algoritmo declarado em cada linha, adotar Argon2id depois é aditivo: valida-se o hash
antigo com o algoritmo que ele próprio declara e re-hasha no próximo login bem-sucedido, que
é o único momento em que a senha em claro existe. Migração preguiçosa, sem reset em massa e
sem janela de indisponibilidade. A mesma mecânica serve para subir os parâmetros do scrypt
sem trocar de algoritmo.

Regra derivada: quem valida senha **nunca** assume o algoritmo da política atual. Lê o que a
linha declara, valida com aquilo, e só então compara com a política para decidir se re-hasha.

### Parâmetros, e de onde vêm

`N = 2^16` (`ln=16`), `r = 8`, `p = 2`.

É uma das combinações que a *OWASP Password Storage Cheat Sheet* lista explicitamente como
equivalentes para scrypt: a primeira escolha é `N=2^17, r=8, p=1`, e `N=2^16, r=8, p=2` é a
alternativa imediata, com o `p` compensando a metade de memória. A forma dos parâmetros e o
custo `128 * N * r` vêm da RFC 7914 (§2), que documenta scrypt e cujo exemplo de login
interativo é `N=2^14, r=8, p=1` — de 2009, e por isso baixo demais hoje.

`128 * 2^16 * 8 = 64 MiB` por hash. Número escolhido com fonte, não no olho.

**Armadilha concreta do CPython:** `hashlib.scrypt` tem `maxmem=0` por padrão, que cai no
limite do OpenSSL de 32 MiB — com estes parâmetros ele **levanta erro**. O `maxmem` é
calculado a partir de `N`, `r` e `p` e passado explicitamente, e existe teste que o prova:
do contrário o próximo a subir `N` descobre isso em produção.

### O custo é superfície de ataque

scrypt é memory-hard por construção — é disso que vem a resistência a GPU. Mas 64 MiB por
hash significa que 20 logins simultâneos são 1,3 GiB, e que um endpoint de login sem limite
é negação de serviço barata: o atacante gasta uma requisição, o servidor gasta 64 MiB.

Duas defesas, em lugares diferentes:

- **Concorrência limitada no passo de hash**, aqui: um semáforo em `core-tenancy` cobre
  quantos hashes rodam ao mesmo tempo. Quem conhece o custo em memória é quem escolheu os
  parâmetros, então o limite mora do lado deles.
- **Limite por IP ou origem**, em `core-007`: é HTTP, e não existe aqui.

Ver também "Tentativa de senha" adiante.

## Trocar de tenant sem digitar a senha de novo

Lacuna real do plano anterior. `autenticar(email, senha, tenant)` grava o tenant na sessão,
o que obrigaria o usuário de dois tenants — justamente o caso de teste central da spec — a
reautenticar para trocar. Não é feature nova: é a consequência direta de ter decidido papel
por tenant.

```python
def trocar_tenant(sessao_atual: str, tenant_destino: UUID) -> str: ...
```

Emite uma **sessão irmã** a partir de uma sessão válida, sem senha, com quatro regras:

1. Exige associação `(usuario, tenant_destino)`. Sem ela, `SemAssociacaoNoTenantError` — trocar
   de tenant nunca concede acesso, só o exerce.
2. O papel é o daquele tenant, resolvido na emissão e **re-resolvido a cada requisição**
   como qualquer sessão. Nada é carregado do tenant de origem.
3. **Herda `expira_em` da sessão mãe, nunca o estende.** Sem isso, trocar de tenant em
   sequência viraria sessão eterna.
4. Guarda `sessao_pai_id`: revogar a mãe revoga as filhas. Uma sessão sobrevivente da que a
   originou é revogação incompleta.

Token de serviço **não** troca de tenant: é emitido para um tenant e nele fica. Automação
que atende dois tenants tem dois tokens, e isso é desejável — o registro da auditoria diz
qual deles agiu.

O ato entra na auditoria do **tenant de destino**, como `tenancy.tenant_trocado`, com o
tenant de origem no detalhe: é lá que o acesso começa a valer.

## Sessão de plataforma é outra tabela

Consequência que só apareceu ao desenhar `trocar_tenant`: `sessao.tenant_id` é `NOT NULL`,
mas o papel de plataforma **não tem tenant ativo**. Ou a coluna vira nulável — o buraco que
**P9** existe para fechar, e a mesma armadilha já recusada na auditoria — ou são duas
tabelas.

São duas: `sessao` (com `tenant_id NOT NULL`) e `sessao_plataforma` (sem a coluna). O ganho
não é estético: uma sessão é de tenant **ou** de plataforma, nunca das duas, e isso passa a
ser verdade no esquema em vez de depender de revisão. A segunda invariante da spec — o papel
de plataforma não lê dado de tenant — não tem como ser violada por engano, porque o
principal de plataforma não tem onde carregar um `tenant_id`.

Um mesmo humano pode ter as duas coisas: linha em `papel_plataforma` e associações de
tenant. São sessões distintas, e trocar entre elas é autenticar de novo — aí sim
deliberadamente, porque é mudança de eixo de autoridade.

Isso acrescenta uma entrada à lista fechada de exceções da spec, o que exige alterar a
spec — feito, com justificativa na tabela.

## Tentativa de senha

Não estava na spec nem no plano, e cairia entre `core-001` e `core-007` sem dono.

Decisão de onde mora, sem implementar agora:

| Controle | Onde | Por quê |
| --- | --- | --- |
| Contador de falhas e bloqueio por usuário | **Aqui**, colunas em `usuarios` ou tabela irmã | É dado, e dado de identidade fica junto da identidade |
| Limite por IP ou origem | `core-007` | É HTTP; não existe neste pacote |
| Concorrência do passo de hash | **Aqui**, em `core-tenancy` | Quem escolheu 64 MiB é quem sabe quantos cabem |

A primeira migração já cria as colunas do contador, mesmo sem ninguém as incrementar ainda:
acrescentá-las depois é migração numa tabela quente, e o custo de criá-las agora é zero.
A spec ganhou a linha correspondente em "Fora de escopo".

### Teste com banco só fala com banco local

Regra, não conveniência. Os testes de `tests/db` e o executor de migração criam e apagam
esquema. Um `VZDR_DATABASE_URL` apontando para outra máquina é a forma mais barata de furar
"nunca contra produção" e "migração só no ambiente local" sem ninguém perceber — não exige
erro de código, só uma variável de ambiente esquecida no shell.

Então a verificação é do código, não da disciplina: **DSN cujo host não seja esta máquina é
recusado**, a menos que `VZDR_PERMITIR_BANCO_REMOTO=1` esteja explícito. A mensagem diz o
host recusado e o que fazer.

A mesma função serve os testes e o executor de migração — uma regra, um lugar. Quem mais
precisa dela é justamente o executor, porque é dele que AGENTS.md fala ao proibir migração
fora do ambiente local.

## Riscos

| Risco | Mitigação |
| --- | --- |
| RLS vaza entre requisições no pool: `SET` em vez de `SET LOCAL` deixa o `tenant_id` grudado na conexão devolvida ao pool | `SET LOCAL` dentro de transação, sempre; teste que reusa a mesma conexão para dois tenants e exige zero linha |
| O dono das tabelas ignora RLS silenciosamente — política existe, não vale para ele | `FORCE ROW LEVEL SECURITY`; a aplicação conecta com papel sem `BYPASSRLS`; teste que prova que o papel da aplicação não vê o outro tenant |
| Teste de isolamento precisa de Postgres, mas `tests/unit` é "sem infraestrutura" e `tests/integration` quer libvirt e QEMU | Terceira pasta, `tests/db`, marcador `db`, alvo `make test-db`. **Fora do `make check`**, que continua determinístico e sem infraestrutura — incluir condicionalmente daria um `check` que passa por não ter rodado nada. A CI sobe o Postgres e roda `test-db` como passo próprio. AGENTS.md e Makefile atualizados junto |
| Auditoria mínima de `core-001` vira dívida quando `core-007` exigir log imutável | Tabelas sem `UPDATE`/`DELETE` concedidos desde a primeira migração; imutabilidade forte é de `core-007` |
| Resolver papel a cada autenticação pesa sob carga | Medir p95 do passo de autenticação desde o começo; cache só com número na mão e ADR (ver Abordagem) |
| Primeiro tenant e primeiro usuário: alguém precisa existir antes de haver quem crie | `scripts/criar-operador-plataforma.py` cria o primeiro papel de plataforma e registra em `auditoria_plataforma`; roda fora da API, nunca por agente de IA. Nome distinto de `scripts/bootstrap.sh`, que prepara o ambiente de desenvolvimento |

## Decisões que viram ADR

- **ADR-0006 — Isolamento de tenant com Row Level Security.** Alternativa razoável existe
  (só o repositório injetando o filtro), a escolha tem custo real (`SET LOCAL` por
  transação, disciplina de pool, papel de banco sem `BYPASSRLS`) e afeta toda tabela de toda
  feature futura. Merece registro.

Não viram ADR, porque decorrem de princípio ou da spec já aprovada: token opaco (spec),
duas tabelas de auditoria (P9), auditoria em pacote próprio (P10, P12), papel resolvido na
autenticação (spec).
