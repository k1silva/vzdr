# Roadmap

Seis marcos. Cada um termina com algo demonstrável e critério de saída objetivo.

## M0 — Fundação (2 semanas)

Repo, `AGENTS.md`, constitution, CI com lint, testes e invariantes, esqueleto do núcleo,
specs `core-001`, `core-002` e `dr-001` aprovadas.

**Sai quando:** `make check` verde na CI e uma spec passou pelo ciclo completo até `tasks`
sem você reescrever à mão.

### Estado em 2026-09-24

| Item | Estado |
| --- | --- |
| Repo, `AGENTS.md`, constitution | feito |
| CI com lint, tipos, testes e invariantes | feito — três jobs: `check`, `banco`, `alvo-py39` |
| Esqueleto do núcleo | feito |
| Spec `core-001` | **passou pelo ciclo completo**: spec, plano e tarefas; T1–T6b implementadas |
| Spec `dr-001` | aprovada, com a telemetria por ciclo do ADR-0013 |
| Spec `core-002` | **rascunho** — sem plano e sem tarefas |

**Falta para fechar:** levar a `core-002` até `tasks`.

O critério "VM de CI com libvirt 9.5 e QEMU 8.2" **saiu deste marco**. Ele nunca foi
cumprido e não podia ser: `tests/integration` nunca rodou, e um marco com critério que
ninguém consegue cumprir é um marco que ninguém usa. Virou item próprio em
"Pré-requisitos de infraestrutura".

O que isso **não** significa: a constituição proíbe mockar libvirt e QMP em teste de
integração, e continua valendo. O mecanismo foi validado contra libvirt e QEMU reais, no
cluster de laboratório, em 18 e 23 de setembro — à mão. Não é mock; é o mesmo teste sem
automação. Ver [validações](validacao/).

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

**Toda linha aqui carrega o método, não só o nome.** Medição registrada sem método é uma
medida diferente cada vez que roda, e a série não serve para comparar nada — que é o único
motivo de medir mais de uma vez. Quando o método mora num ADR, a linha aponta para lá em
vez de repetir, senão os dois divergem e nenhum dos dois é autoridade.

- [x] Censo de discos nos três nós (`scripts/censo-discos.sh`) — feito em 2026-09-23:
      11,83 TiB, 65 VMs, 115 discos.
      Ver [censo](validacao/2026-09-23-censo-do-parque.md)
- [ ] **Taxa real de mudança** (M3 do ADR-0012) — `scripts/medir-taxa-mudanca.sh`, com
      bitmap, em amostra de **5 a 8 VMs cobrindo os perfis**, ao longo de 48 h. O método é
      o do [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md); esta linha dizia "20-30 VMs"
      e divergia dele
- [ ] **Sobrevivência do bitmap à migração automática do VHI** (M4 do ADR-0012) — migrar
      uma VM descartável entre dois nós e conferir se o bitmap persiste. Exige cluster com
      mais de um nó. Bloqueado por [P-001](pendencias.md), chamado aberto com a Virtuozzo:
      a resposta muda como o teste é feito, ou se ele é necessário
- [ ] **Classificação das VMs por tier** — o critério escrito **antes** da lista, e a lista
      derivada dele. Na ordem inversa a classificação vira opinião por VM, e ninguém
      consegue dizer depois por que uma VM ficou no tier que ficou
- [ ] **Vazão real de seed entre os datacenters** (M1 do ADR-0012) — repetir o seed de
      2026-09-23 com `time`, medindo o mesmo volume, para converter tamanho em horas. Sem
      ela, toda estimativa de tempo de resync é chute, inclusive as dos próprios documentos
- [ ] **Custo da mescla de bitmap em função do número de checkpoints retidos** — cronometrar
      a mescla com 1, 2, 4, 8, 16 e 32 checkpoints retidos na mesma VM, e registrar a curva.
      É ela que define o limiar de compactação da
      [`dr-001`](../specs/dr-001-dominio-ciclo/spec.md), e precisa existir antes da `dr-003`.
      Sem a curva, qualquer limiar é chute com cara de número

## Pré-requisitos de infraestrutura

Bloqueiam o M3, não o início.

- [ ] **VM de CI com libvirt 9.5 e QEMU 8.2**, para automatizar `tests/integration`.
      Hoje esses testes rodam à mão contra o laboratório. Bloqueia o M2, cujo critério
      de saída é uma VM replicando 72 h seguidas — fazer isso à mão não escala.

      *Por que aqui e não em [`pendencias.md`](pendencias.md):* o critério de entrada de
      lá exige as três coisas ao mesmo tempo, e falta a decisiva — **dono fora do
      repositório**. Provisionar um runner é trabalho que controlamos. Ele atende as
      outras duas (bloqueia critério de marco, citado em mais de um documento), e é bom
      que o registro de pendências exclua alguma coisa: critério que aceita tudo vira
      depósito.

- [ ] Conta de serviço de API nos dois clusters
- [ ] Capacidade confirmada no DC-2
- [ ] Túnel WireGuard entre os datacenters
- [ ] VM de CI com libvirt 9.5 e QEMU 8.2
