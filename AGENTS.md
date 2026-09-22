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
make lint         # ruff check
make fmt          # ruff format + fix
make typecheck    # mypy
make test         # pytest tests/unit — rápido, sem infraestrutura
make test-int     # pytest tests/integration — exige libvirt + qemu reais
make invariants   # checadores de invariante (pureza, tenant_id, fronteiras)
make check        # lint + typecheck + test + invariants
make db-up        # PostgreSQL local
```

`make check` tem que passar antes de qualquer commit. Sem exceção.

## Versão de Python

O **alvo de execução é 3.9** — é a versão dos hypervisors, onde o agente roda.
Desenvolva no que quiser, mas não use sintaxe de 3.10+ (`match`, `X | Y` em anotação
sem `from __future__ import annotations`, etc.). O `ruff` com `target-version = "py39"`
é quem verifica isso.

Se o `mypy` reclamar de `python_version = "3.9"` por ser antigo demais, suba só o mypy
para 3.10 e mantenha o ruff em py39 — o ruff é quem garante a compatibilidade de sintaxe.

## Estrutura

```
packages/core-*        capacidades do núcleo, compartilhadas por todas as features
packages/tool-dr       a feature de DR
packages/agent         roda no hypervisor; capacidades plugáveis
packages/cli           CLI, cliente da mesma API que a interface consome
specs/                 uma pasta por feature: spec.md, plan.md, tasks.md
docs/adr/              decisões de arquitetura registradas
tests/unit             sem infraestrutura
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
- Nenhuma dependência nova sem justificativa na spec ou num ADR.

## Fronteiras — a CI verifica

- `vzdr.core.domain` não importa nada de IO: sem libvirt, sem rede, sem banco, sem subprocess.
- Nenhum módulo do núcleo importa de `vzdr.tools.*`. O núcleo não conhece as features.
- Uma feature não importa de outra feature. Conversam por eventos.
- O agente não fala com o banco. Fala com a API.
- `tenant_id` em toda tabela, desde a primeira migração.

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
