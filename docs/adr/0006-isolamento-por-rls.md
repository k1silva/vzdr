# ADR-0006: Isolamento de tenant com Row Level Security

**Data:** 2026-09-23
**Status:** aceito

## Contexto

`core-001` tem um critério de aceite que soa modesto e não é: *uma consulta sem filtro de
tenant falha num teste automatizado*. Falha — não "é pega na revisão", não "é convenção".

A forma usual de isolar tenant é disciplina: todo `SELECT` leva `where tenant_id = %s`,
e um repositório injeta o filtro. Funciona enquanto todo mundo passa pelo repositório.
O problema não é o código que se escreve pensando nisso; é o `JOIN` de diagnóstico às três
da manhã, a consulta de relatório, o `COUNT` que alguém achou inofensivo, e a feature que
daqui a dois anos acessa uma tabela que o repositório de hoje não conhece.

A conta do erro é assimétrica. Esquecer o `WHERE` numa tabela de log dá um número errado;
esquecer numa tabela de VM protegida mostra a infraestrutura de um cliente para outro. Num
produto de DR vendido a vários clientes, é o tipo de falha que encerra o produto.

P9 põe `tenant_id` em toda tabela que guarda dado de tenant. Isso torna o isolamento
*possível*, não *garantido*: a coluna existe, resta alguém usá-la em toda consulta.

## Decisão

Row Level Security no PostgreSQL, como segunda camada, abaixo do repositório.

- `ENABLE ROW LEVEL SECURITY` **e** `FORCE ROW LEVEL SECURITY` em toda tabela com
  `tenant_id`. Sem `FORCE`, o dono da tabela ignora a política — e o dono é quem roda as
  migrações.
- Política sobre `current_setting('vzdr.tenant_id', true)`.
- A aplicação conecta com um papel de banco **sem** `BYPASSRLS` e que não é dono das
  tabelas. O papel que migra é outro.
- O contexto entra com `SET LOCAL vzdr.tenant_id`, sempre dentro da transação.

Sem contexto, a consulta devolve zero linha. Não é erro, é vazio — o que basta para o
teste, porque o teste afirma que o outro tenant não aparece.

As três camadas, e o que cada uma pega:

| Camada | Pega | Não pega |
| --- | --- | --- |
| Repositório injetando o filtro | O caminho normal, com mensagem boa | Quem não passa por ele |
| RLS com `FORCE` | Qualquer consulta, de qualquer código, inclusive `psql` | Erro na própria política |
| `check_tenant_id.py` na CI | Tabela nova sem a coluna | O que já existe |

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Só o repositório injetando o filtro | Garante o código que passa por ele. O vazamento vem justamente do que não passa, e não há como provar a ausência |
| Um schema por tenant | Isolamento forte e migração multiplicada por tenant; `core-005` (inventário) e qualquer consulta agregada da plataforma viram união dinâmica de N schemas |
| Um banco por tenant | Mesma objeção, mais cara, e P12: não construir para uma escala que ainda não existe |
| RLS sem `FORCE` | O dono da tabela ignora a política em silêncio. Uma proteção que o caminho mais provável de administração não respeita é pior que nenhuma, porque dá confiança |
| Adiar para quando houver o segundo tenant | O retrofit que P9 existe para evitar. Ligar RLS com dados dentro é migração com janela |

## Consequências

Fica mais fácil dormir. O isolamento deixa de depender de toda consulta futura estar certa
e passa a depender de uma política estar certa — uma coisa, num lugar, testável.

Fica mais difícil em quatro pontos concretos:

**Disciplina de pool.** `SET` em vez de `SET LOCAL` gruda o `tenant_id` na conexão, que
volta ao pool e serve a próxima requisição, de outro tenant. É a pior falha possível nesta
área e o teste que a cobre reusa deliberadamente a mesma conexão para dois tenants.

**Zero linha não diz por quê.** Uma consulta sem contexto devolve vazio, não erro, e "sumiu
o dado" custa a depurar. Por isso o repositório continua existindo: ele é quem dá a
mensagem boa. RLS é a rede, não a porta.

**Dois papéis de banco.** Quem migra e quem consulta são papéis diferentes, e a conexão da
aplicação não pode ser superusuário. Isso precisa estar no `docker-compose.yml` local, não
só em produção, ou a rede só existe onde ninguém testa.

**Custo de planejamento.** A política entra em todo plano de consulta. Não é grátis, e em
tabela grande com índice mal escolhido aparece. A medição fica para quando houver volume;
até lá, correção antes de desempenho.

Uma coisa que esta decisão **não** resolve: o papel de plataforma. Ele não tem `tenant_id`,
então nenhuma política o alcança. O que o mantém fora dos dados de tenant é o esquema —
`sessao_plataforma` separada de `sessao`, e um principal que não tem onde carregar um
tenant. RLS protege o eixo; o eixo em si é desenho de tabela.
