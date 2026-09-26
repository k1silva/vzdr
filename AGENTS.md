# AGENTS.md

Instruções para agentes de IA que trabalham neste repositório.
Leia também `.specify/memory/constitution.md` — os princípios de lá valem sobre tudo.

## O que é o vzdr

Plataforma de operação de infraestrutura. Um app, várias features.
A primeira é **DR**: replicação incremental de VMs entre dois clusters Virtuozzo
Hybrid Infrastructure, com failover.

Documentação em `docs/`. A fonte da verdade de cada feature é a spec em `specs/`.
Se o código diverge da spec, a spec está errada — atualize-a.

## Comandos

```bash
make setup        # venv + dependências de desenvolvimento
make lint         # ruff check + ruff format --check
make fmt          # ruff format + fix
make typecheck    # mypy
make test         # pytest tests/unit — rápido, sem infraestrutura
make test-db      # pytest tests/db — exige PostgreSQL local (make db-up)
make test-int     # pytest tests/integration — exige libvirt + qemu reais
make invariants   # checadores de invariante (pureza, tenant_id, fronteiras)
make check        # lint + typecheck + test + invariants
make db-up        # PostgreSQL local
```

`make check` tem que passar antes de qualquer commit. Sem exceção.

**Limite o commit, não o `add`.** `git add <caminhos> && git commit` leva **tudo que o
índice acumulou**, inclusive o que ficou de um `git add -A` anterior — já aconteceu duas
vezes aqui, com um commit de infraestrutura engolindo os arquivos de outra fatia.
`git commit -- <caminhos>` leva só o que se nomeia.

Com uma pegadinha: `git commit -- <caminhos>` **não inclui arquivo novo**. Para arquivo
não rastreado, `git add` primeiro e depois `git commit -- <os mesmos caminhos>` — o `add`
põe no índice, e o `--` limita o que sai dele. Confira o `--stat` antes de considerar
feito.

**Não canalize comando de verificação.** `make check | tail` devolve o código de saída
do `tail`, não o do `make` — o comando reprova e o `&&` seguinte roda assim mesmo. Já
aconteceu: um commit entrou com arquivo não formatado por causa disso. Se a saída é
longa demais para ler, o problema é a saída, não a leitura.

`make check` não inclui `test-db` nem `test-int`: ele é determinístico e não depende de
infraestrutura. Quem mexe em esquema, isolamento de tenant ou migração roda `make test-db`
também — a CI roda os dois.

**A CI chama alvos do Makefile e nunca repete os comandos deles.** Um lugar só define
como se roda o projeto. Ferramenta nova, alvo novo ou dependência nova entram no
`Makefile`; o workflow continua chamando `make <alvo>`. Foi a repetição que deixou o
`psycopg` no `make setup` e fora do YAML, e a CI quebrou num passo que localmente
passava.

## Versão de Python

**O agente é 3.9, não o projeto.** A restrição vem dos hypervisors, onde só o agente
roda. O control plane roda onde escolhemos: 3.11.

| Onde | Alvo | Quem verifica |
| --- | --- | --- |
| `packages/agent` e o fecho de dependências dele (hoje `packages/core-domain`) | 3.9 | `ruff` com `target-version = "py39"` no pyproject do próprio pacote |
| Todo o resto | 3.11 | `ruff` na raiz |

Nos pacotes restritos, nada de sintaxe 3.10+ (`match`, `X | Y` em anotação sem
`from __future__ import annotations`).

Um pacote restrito **não pode importar** pacote sem a restrição: quebraria no hypervisor
em tempo de import, não na CI. `tests/invariants/check_alvo_py39.py` verifica o fecho.

O `mypy` não aceita `python_version` por módulo — é opção global. Por isso o `make
typecheck` roda duas vezes: a global em 3.11 e uma segunda sobre os dois pacotes
restritos. Essa segunda usa `--python-version 3.10`, que é o piso que o mypy atual
aceita — **quem garante a sintaxe de 3.9 é o `ruff`**, como já era a regra. Ver
`docs/adr/0007-alvo-de-python-por-pacote.md`.

## Estrutura

```
packages/core-*        capacidades do núcleo, compartilhadas por todas as features
packages/tool-dr       a feature de DR
packages/agent         roda no hypervisor; capacidades plugáveis
packages/cli           CLI, cliente da mesma API que a interface consome
specs/                 uma pasta por feature: spec.md, plan.md, tasks.md
docs/adr/              decisões de arquitetura registradas
tests/unit             sem infraestrutura
tests/db               exige PostgreSQL local; isolamento de tenant, RLS, migrações
tests/integration      exige libvirt 9.5 e QEMU 8.2 reais
tests/invariants       checadores que rodam na CI
```

Os módulos vivem sob o namespace `vzdr`:

```python
from vzdr.core.domain import ...
from vzdr.core.connections import ...
from vzdr.tools.dr import ...
```

`vzdr/`, `vzdr/core/` e `vzdr/tools/` são namespace packages (PEP 420) — **não** crie
`__init__.py` neles. Só os pacotes folha têm `__init__.py`.

## Convenções

- Tipagem obrigatória em assinaturas públicas. `mypy --strict` em `vzdr.core.domain`.
- `ruff` para estilo e ordenação de imports. `make fmt` antes do commit.
- Termos de negócio em português (`ciclo`, `janela`, `ponto_de_recuperacao`); o resto em inglês.
- Classe de exceção termina em `Error` (`TokenInvalidoError`, `BancoRecusadoError`).
  O termo de negócio continua em português; `Error` é marcador de tipo, não palavra
  de negócio. É a regra `N818` do ruff, e ela fica ligada: um `ignore` de regra de
  estilo vira imposto de leitura para quem chegar depois perguntando o porquê.
- **Caminho que nunca executa onde você testa precisa de teste que o force.**
  `CREATE ROLE` com senha só roda quando o papel ainda não existe; localmente ele
  existia desde a primeira execução, e o bug foi para a CI. Apague o estado e rode de
  novo, ou escreva o teste que cria a condição.
- **Erro que não distingue causas mente sobre o diagnóstico.** Um `except` que trata
  toda falha do driver como "banco fora do ar" transforma erro de sintaxe em caça ao
  PostgreSQL. Separe falha de conexão de falha de execução, e preserve o erro cru (P8).
- **Checador de coerência entre documento e realidade é sempre bidirecional.** Afirmar
  que algo é verificado exige o mecanismo existir; afirmar que **não** é verificado exige
  que ele não exista. Olhar um sentido só fecha metade da classe e dá a sensação de ter
  fechado inteira — já aconteceu três vezes: no contrato de eventos, na guarda de
  terceiros no hypervisor, e num ADR que dizia depender de revisão humana quando já não
  dependia.
- **Verificação que não verifica é pior que verificação ausente**, porque dá confiança.
  Dois casos já mordidos: em Postgres, `rolsuper` e `rolbypassrls` têm que ser checados
  **juntos** — `FORCE ROW LEVEL SECURITY` não alcança superusuário, então um papel
  superusuário passa num teste que olha só `rolbypassrls` e ignora toda a política.
  Quando escrever um teste de controle de segurança, mute o controle e confirme que o
  teste reprova.
- Seção de configuração do `mypy` que não casa com nenhum módulo **falha o build**.
  O `mypy` trata isso como nota e sai com código 0, então a regra daquela seção
  simplesmente deixa de ser aplicada sem ninguém ver. `scripts/checar_mypy.py`
  transforma a nota em erro.
- Nenhuma dependência nova sem justificativa na spec ou num ADR.

## Fronteiras — a CI verifica

- `vzdr.core.domain` não importa nada de IO: sem libvirt, sem rede, sem banco, sem subprocess.
- Nenhum módulo do núcleo importa de `vzdr.tools.*`. O núcleo não conhece as features.
- Uma feature não importa de outra feature. Conversam por eventos.
- O agente não fala com o banco. Fala com a API — e isso passou a ser **verificado**:
  `psycopg` não é da biblioteca padrão e não está em `TERCEIROS_PERMITIDOS`, então
  `check_alvo_py39.py` recusa. Até a core-002 esta linha estava sob "a CI verifica"
  sem nenhuma CI verificando.
- Pendência de `docs/pendencias.md` com data de revisão vencida falha o build. É o
  único checador que falha por tempo passar, e não pelo que você mudou — o conserto
  legítimo é mudar o estado ou mudar a data com motivo.
- `tenant_id` em toda tabela que guarda dado de tenant, desde a primeira migração.
  A lista de exceções é fechada e justificada em `specs/core-001-tenancy/spec.md`;
  acrescentar exceção é alterar a spec, não editar o checador.

## O que NUNCA fazer

- Executar comando contra cluster de produção. Desenvolvimento usa o laboratório.
- `git push` para `main`, ou commit sem revisão humana do diff.
- Escrever credenciais, certificados ou `.env` no repositório.
- Apagar checkpoint, bitmap, snapshot ou volume sem confirmação explícita do humano.
- Rodar migração de banco fora do ambiente local.
- Mockar libvirt ou QMP em teste de integração — o comportamento que importa está nas
  bordas reais do QEMU.

## Ao implementar uma tarefa

1. Leia `specs/<id>/spec.md` antes de escrever código.
2. Escreva o teste junto com a implementação, nunca depois.
3. Cubra o comportamento em falha, não só o caminho feliz.
4. Rode `make check`.
5. Se descobriu algo que a spec não previa, **atualize a spec** e diga isso no resumo.

Uma tarefa, um commit. Se o diff ficou grande demais para ser revisado de uma sentada,
a tarefa estava mal fatiada — pare e proponha a divisão.

## Branch e PR

- **Nunca commitar direto em `main`.** Um branch por **fatia revisável**, não por spec
  inteira: `core-001-dominio`, `core-001-sessao`, `dr-003-checkpoint`. Uma spec de 14
  tarefas vira um PR que ninguém revisa e mantém `main` vermelho por semanas.
- A fatia é o maior conjunto de tarefas que alguém revisa de uma sentada e que deixa
  `main` coerente ao ser mesclado. Na dúvida, menor.
- Uma tarefa, um commit, no branch da fatia. Mensagem diz o *porquê*, não só o quê.
- `make check` verde antes de cada commit.
- O merge em `main` é por PR, com revisão humana do diff. Nenhum agente de IA commita
  sem que um humano tenha lido o diff, e nenhum faz `git push` para `main`.
- Mudança de infraestrutura compartilhada — CI, Makefile, checador de invariante — vai
  em commit próprio, separado da tarefa que a motivou. Quem revisa uma tarefa não deveria
  ter que revisar o build junto.
- **Todo PR declara quem revisou o diff.** Três linhas, sempre, respondidas — quem
  revisou, se um humano leu o diff, e se o clique do merge foi delegado. As três, porque
  só a primeira é respondível com verdade por quem delegou: "revisado por: k1silva" é
  verdadeiro no GitHub mesmo quando ninguém leu, e aí a declaração não declara nada.
- **A declaração é estrutura, não disciplina.** O `.github/pull_request_template.md` traz
  as linhas por responder, então ela não depende de alguém lembrar de escrever — depende
  de alguém lembrar de apagar, que é o sentido certo do esforço. Na forma anterior desta
  regra, o esquecimento produzia silêncio, e silêncio é indistinguível do caso normal.
- **Delegação é decisão do humano, vale para aquele PR, e pode cobrir ler e apertar.** Um
  humano pode delegar a revisão do diff a um agente, e também o clique do merge. Não é
  violação; é escolha dele, e fica registrada. O que não vale é delegação como **modo
  permanente**: delegação sem escopo é override de banda sem prazo, que o
  [ADR-0013](docs/adr/0013-orcamento-de-banda-e-janelas.md) já recusou pelo mesmo motivo —
  o temporário vira permanente e ninguém lembra por quê.
- **`git push` direto para `main` continua fora do alcance de qualquer agente**, em
  qualquer arranjo. O que a delegação dispensa é a leitura e o clique, nunca a decisão de
  quem manda.
- `tests/invariants/check_declaracao_de_revisao.py` verifica **que as linhas foram
  respondidas**, e o nome dele diz só isso. Ele não verifica que a revisão aconteceu, e
  nunca vai: isso não é fato do repositório. A doença deste projeto não é checador que
  verifica pouco — é checador que afirma mais do que verifica. Roda em `make
  declaracao-revisao`, fora do `make invariants`, porque precisa do corpo do PR; e
  **falha sem entrada**, em vez de passar em silêncio. Rótulo que aparece duas vezes no
  corpo também reprova: corpo de PR cita documento, e escolher a primeira ocorrência em
  silêncio faria um PR que não respondeu passar, se a citada vier antes e estiver
  respondida no exemplo.
- **Para citar os rótulos num PR, use bloco de código** — cerca de crases ou tis, três ou
  mais, ou bloco indentado.
  O checador os ignora, então PR que discute a própria regra cita à vontade. Fora de
  bloco, o rótulo tem que começar na margem e aparecer uma vez só. A escolha foi entre
  isto e pedir que ninguém escrevesse o rótulo literal; a segunda custa disciplina, e
  disciplina é o que este projeto troca por estrutura sempre que dá.
- Com a declaração em todo PR, delegação vira **contável**. Se um dia for preciso
  restringir delegação por tipo de mudança — migração, código de segurança —, a regra se
  escreve varrendo os PRs mesclados, com dado em vez de intuição.
- **Mudança em workflow só está pronta quando uma execução nova aparecer verde.** Não
  basta o YAML parecer certo: ausência de check é indistinguível de sucesso em quase toda
  interface — um job que deixou de existir, um nome que mudou ou um gatilho que não casa
  aparecem como "nada falhou". Confira que o job rodou, não só que não reprovou.
