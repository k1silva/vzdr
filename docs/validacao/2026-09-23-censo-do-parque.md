# Censo do parque — 2026-09-23

> **Este é o laboratório da 4EDGE**, não o ambiente do cliente-alvo. O cliente tem 40 TB e
> distribuição ainda desconhecida. Os números abaixo dimensionam o laboratório e validam o
> método; **não** servem de proxy para o cliente em nenhuma decisão de priorização.

Primeira passada do `censo-discos.sh` nos três nós. Somente leitura: `virsh domblklist`
mais `qemu-img info -U`. Nenhum checkpoint, nenhum bitmap, nenhuma escrita.

Segunda passada prevista para 2026-09-25, comparada com `censo-delta.sh`.

## Totais

| Nó | VMs | Discos de dado | Alocado |
|---|---|---|---|
| vhi-hv01 | 12 | 18 | 3.163,54 GiB |
| vhi-hv02 | 24 | 44 | 3.281,71 GiB |
| vhi-hv03 | 29 | 53 | 5.664,22 GiB |
| **Total** | **65** | **115** | **12.109,47 GiB — 11,83 TiB** |

O laboratório tem **11,83 TiB** reais. Os "40 TB" que orientaram o dimensionamento inicial
são do **cliente-alvo**, não daqui — medição M2 do [ADR-0012](../adr/0012-resposta-a-perda-de-bitmap.md),
ainda pendente.

A tabela de tempo de seed do ADR-0008 deve citar as duas escalas separadamente: 11,83 TiB
para o laboratório, 40 TB como ordem de grandeza do cliente, com a ressalva de que a
distribuição lá é desconhecida.

## Formatos: `raw` deixou de ser problema

| Formato | Discos | Alocado |
|---|---|---|
| qcow2 | 91 | 12.108 GiB |
| raw | 24 | **1,50 GiB** |

Os 24 discos `raw` têm 0,06 GiB cada e estão todos no target `sda`: são config drives
gerados pelo Nova. Não são dado de cliente e **não precisam ser replicados** — no failover
o catálogo recria a VM e o Nova gera um novo config drive.

Isso resolve o item "origem `raw`" que estava em aberto na `dr-006`: passa de limitação a
**exclusão por desenho**. Todos os 115 discos de dado são qcow2 e suportam checkpoint. O
escopo do mecanismo é o parque inteiro.

## Distribuição: um degrau, não uma curva

| VM | Nó | Alocado | % do parque |
|---|---|---|---|
| `instance-0000025d` | hv03 | 3.836,14 GiB | 31,7% |
| `instance-00000261` | hv01 | 2.834,61 GiB | 23,4% |
| `instance-00000189` | hv02 | 2.546,12 GiB | 21,0% |
| **Top 3** | | **9.216,87 GiB** | **76,1%** |

As outras 62 VMs somam 2.892,60 GiB — média de 47 GiB cada. A quarta maior é a
`instance-0000025e`, com 607,57 GiB; depois dela vêm 266,70, 220,92, 190,74, 175,14 e
154,97 GiB.

**Três VMs são três quartos do parque.** Qualquer decisão de dimensionamento — banda,
janela de resync, política de placement, capacidade no destino — é decidida por elas. E
qualquer política baseada em tamanho tem um ponto de corte óbvio entre 607 GiB e 2,5 TiB.

É esta tabela que fundamenta a decisão 3 do
[ADR-0012](../adr/0012-resposta-a-perda-de-bitmap.md).

## Multi-disco é a regra, não a exceção

115 discos para 65 VMs. A `instance-00000189` sozinha tem 8. O agrupamento atômico de
snapshots por VM (ADR-0010, P5) não é requisito teórico: a maioria do volume do parque está
em VMs de vários discos.

## Em aberto

- Segunda passada em 2026-09-25 para o piso de crescimento diário.
- Vazão real de seed entre os datacenters. O seed validado transferiu 5.535,6 MiB, mas sem
  cronometragem. Sem esse número, toda estimativa de tempo de resync é chute.
- Taxa de mudança real (fase 2, com bitmap em amostra de 5 a 8 VMs cobrindo os perfis). O
  censo dá piso de crescimento, não taxa de sobrescrita, e é a taxa que dimensiona banda.
