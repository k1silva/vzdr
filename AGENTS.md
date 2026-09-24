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
- O agente não fala com o banco. Fala com a API.
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
- **Mudança em workflow só está pronta quando uma execução nova aparecer verde.** Não
  basta o YAML parecer certo: ausência de check é indistinguível de sucesso em quase toda
  interface — um job que deixou de existir, um nome que mudou ou um gatilho que não casa
  aparecem como "nada falhou". Confira que o job rodou, não só que não reprovou.
