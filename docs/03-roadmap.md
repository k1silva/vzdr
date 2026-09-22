# Roadmap

Seis marcos. Cada um termina com algo demonstrável e critério de saída objetivo.

## M0 — Fundação (2 semanas)

Repo, `AGENTS.md`, constitution, CI com lint, testes e invariantes, VM de CI com libvirt
9.5 e QEMU 8.2, esqueleto do núcleo, specs `core-001`, `core-002` e `dr-001` aprovadas.

**Sai quando:** `make check` verde na CI e uma spec passou pelo ciclo completo até `tasks`
sem você reescrever à mão.

## M1 — Núcleo testável (2 semanas)

`core-001`, `core-003`, `dr-001`, `dr-002`. Máquina de estados, descoberta de discos,
estado durável. Nada ainda copia byte.

**Sai quando:** a máquina de estados cobre todos os cenários de falha, com teste para cada
um, rodando sem hypervisor em menos de 2 segundos.

## M2 — Ciclo real (3 a 4 semanas)

`dr-003`, `dr-004`, `dr-005`, `core-004`. O agente replica de verdade, multi-disco, com
quiesce e reconciliação.

**Sai quando:** uma VM de vários discos replica por 72 h seguidas no laboratório,
sobrevivendo a uma queda de link provocada e a um reinício do agente, sem resync completo.

## M3 — Destino completo (3 semanas)

`dr-006`, `dr-007`, `dr-008`. Receptor provisionando, snapshots agrupados, TLS ponta a ponta.

**Sai quando:** cinco VMs replicam do DC-1 para o DC-2 pela WAN, com pontos de recuperação
visíveis no painel do VHI, e um deles é montado e verificado em máquina dedicada.

## M4 — Plataforma (4 semanas)

`core-005`, `core-006`, `core-007`, `dr-009`. Inventário, eventos, API, auditoria, plano de
failover em dry-run. A interface começa aqui.

**Sai quando:** o plano de failover sai sem pendências para o tier crítico, e tudo que a
interface faz também acontece pela CLI.

## M5 — Failover (4 semanas)

`dr-010`, `dr-011`. Execução, test-failover isolado, failback.

**Sai quando:** um test-failover completo sobe as VMs do tier crítico em rede isolada, com
aplicação respondendo, sem tocar em produção — e o failback devolve a operação ao DC-1
transferindo só o delta.

## Em paralelo — Fase 0 de medição

Roda junto com M0 e M1, precisa fechar antes do M3, porque dimensiona o storage do DC-2.

- [ ] Censo de formatos em todos os nós (`scripts/censo-formatos.sh`)
- [ ] Taxa de mudança em 20-30 VMs por 48 h (`scripts/medir-taxa-mudanca.sh`)
- [ ] Teste de sobrevivência do bitmap à migração automática do VHI
- [ ] Classificação das VMs por tier

## Pré-requisitos de infraestrutura

Bloqueiam o M3, não o início.

- [ ] Conta de serviço de API nos dois clusters
- [ ] Capacidade confirmada no DC-2
- [ ] Túnel WireGuard entre os datacenters
- [ ] VM de CI com libvirt 9.5 e QEMU 8.2
