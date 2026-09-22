# Specs

Uma pasta por feature, com `spec.md`, `plan.md` e `tasks.md`. Templates em `_template/`.

## Ordem de construção

Núcleo e feature intercalados: cada capacidade do núcleo nasce quando o DR precisa dela.

| # | Spec | Entrega | Depende de | Marco |
| --- | --- | --- | --- | --- |
| core-001 | Tenancy e identidade | Usuários, tenant, papéis, verificação de permissão | — | M0 |
| core-002 | Conexões e conectores | Registro de sistemas externos, conector tipado, cofre, health check | core-001 | M0 |
| dr-001 | Domínio e máquina de estados | VM protegida, ciclo, janela, ponto de recuperação | core-001 | M1 |
| dr-002 | Descoberta de discos e bitmaps | node-name, inventário de discos, leitura de bitmaps | dr-001 | M1 |
| core-003 | Motor de trabalho | Fila durável, estado, retomada, agendamento | core-001 | M1 |
| dr-003 | Ciclo de replicação multi-disco | Checkpoint atômico, merge, backup job, commit | dr-001, dr-002, core-003 | M2 |
| dr-004 | Quiesce com watchdog | freeze/thaw garantido, nível de consistência registrado | dr-003 | M2 |
| dr-005 | Reconciliação e resync | Detecção de divergência, decisão de resync | dr-003 | M2 |
| core-004 | Frota de agentes | Registro, versão, saúde, comando | core-002 | M2 |
| dr-006 | Receptor: volumes e export | Provisiona volume Cinder, anexa, expõe NBD | dr-001, core-002 | M3 |
| dr-007 | Pontos de recuperação e retenção | Snapshot Cinder por VM, política, expurgo | dr-006 | M3 |
| dr-008 | Transporte TLS | Credenciais, nó destino, throttle | dr-003, dr-006 | M3 |
| core-005 | Inventário | VMs, volumes, redes, hosts; sincronização e drift | core-002 | M4 |
| core-006 | Eventos e webhooks | Barramento de eventos, assinatura externa, entrega com retry | core-003 | M4 |
| core-007 | API e auditoria | FastAPI, OpenAPI, autenticação, RBAC, log imutável | core-001, core-003 | M4 |
| dr-009 | Plano de failover | Mapeamento DC1→DC2, preflight, dry-run | core-005 | M4 |
| dr-010 | Failover e test-failover | Clone isolado, portas, VMs, ordem de boot | dr-007, dr-009 | M5 |
| dr-011 | Failback | Reversão do fluxo, só o delta do período de desastre | dr-010 | M5 |

A interface começa depois de `core-007`, consumindo a API. Pode correr em paralelo assim
que o contrato OpenAPI estabilizar.

## O que toda spec responde

1. **Comportamento normal** — o caminho feliz, passo a passo.
2. **Comportamento em falha** — o que acontece em cada ponto de falha e o estado resultante.
3. **O que nunca pode acontecer** — as invariantes, ligadas aos princípios da constitution.
4. **Critério de aceite** — os testes que provam que está pronto.
5. **Fora de escopo** — explicitamente, para o agente não inventar.

O item 2 é o que mais rende num sistema de DR. O caminho feliz é a parte fácil.
