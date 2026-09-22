# vzdr

Plataforma de operação de infraestrutura. Um app, várias features.

A primeira feature é **DR** — replicação incremental de VMs entre dois clusters
Virtuozzo Hybrid Infrastructure, com pontos de recuperação e failover.

## Estado

Em construção. Marco atual: **M0 — Fundação**. Veja `docs/03-roadmap.md`.

O mecanismo central de replicação já foi validado contra um cluster real: carga inicial
de 8,7 GiB num volume de 80 GiB, seguida de um ciclo incremental de 16,7 MiB — 0,19%.
Detalhes em `docs/01-arquitetura-dr.md`.

## Começar

```bash
./scripts/bootstrap.sh
```

Depois leia `PRIMEIROS-PASSOS.md`.

## Como trabalhamos

Spec-driven development: a especificação é a fonte da verdade, o código é derivado dela.
Leia `CONTRIBUTING.md` antes da primeira tarefa, e `AGENTS.md` se você for um agente de IA.

## Mapa

| Pasta | O que tem |
| --- | --- |
| `docs/` | Visão, arquitetura, roadmap e ADRs |
| `specs/` | Uma pasta por feature: spec, plano e tarefas |
| `packages/core-*` | Capacidades do núcleo |
| `packages/tool-dr` | A feature de DR |
| `packages/agent` | Roda no hypervisor |
| `tests/` | unit, integration, e2e, invariants |
| `deploy/` | systemd, migrações, empacotamento |
