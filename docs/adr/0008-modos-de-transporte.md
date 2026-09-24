# ADR-0008: Modos de transporte entre origem e destino

**Data:** 2026-09-23
**Status:** aceito

## Contexto

O ciclo de replicação copia blocos de um disco vivo no hypervisor de origem para um
destino remoto. Quem abre a conexão TCP é o processo QEMU do hypervisor — não a VM
protegida, não a control plane. Isso tem duas consequências que definem o desenho:

1. O caminho de rede precisa existir **a partir do hypervisor**, na rede de gerência.
   Uma VPN de projeto (VPNaaS do Neutron) liga sub-redes de tenant e normalmente **não**
   cobre o hypervisor. Verificado no laboratório: o nó do DC-1 não alcança a VM do DC-2
   pela VPN do projeto.
2. Exigir que o cliente publique porta de entrada é inviável comercialmente. Times de
   segurança recusam, e o projeto morre na reunião. Saída NAT, ao contrário, é universal.

O QEMU suporta os dois sentidos, e ambos os primitivos já foram validados no cluster:

- **push** — `blockdev-backup` com nó NBD remoto. O hypervisor disca para fora.
- **pull** — `nbd-server-start` + `block-export-add` na origem, exportando o disco com o
  meta-contexto `qemu:dirty-bitmap:<nome>`. O destino disca para fora e lê só os extents
  sujos.

## Decisão

O transporte é **configuração por par de sites**, com quatro modos de dados e um modo de
carga inicial. O agente não escolhe sozinho: o modo é determinado no onboarding do site e
gravado no catálogo.

| Modo | Quem disca | Exige entrada em | Uso |
|---|---|---|---|
| `push` | hypervisor de origem | destino | **padrão do plano de dados** |
| `jump-ssh` | os dois, para o jump | ninguém | fallback quando o cliente não libera saída direta |
| `pull` | worker no destino | origem | cliente que só aceita ser lido |
| `rendezvous-wg` | os dois, para o hub | ninguém | seed grande em link com perda |
| `seed-offline` | — | — | **carga inicial acima de alguns TB** |

**`push` é o padrão do plano de dados.** Um único IP público, no destino, sob controle do
provedor. O cliente não publica nada: só precisa de saída para um `IP:porta`. Validado de
ponta a ponta entre datacenters em 2026-09-23 (ver `docs/validacao/`).

**O canal de controle é sempre `jump-ssh`**, independente do modo de dados. É leve,
universal e auditável.

**Autenticação é TLS mútuo do NBD, sempre**, em todos os modos, inclusive dentro de túnel.
`verify-peer=on` nos dois lados e `authz-simple` restringindo o CN do cliente. Regra de
firewall por `/32` é segunda camada, não a primeira.

### O modo `pull` exporta somente leitura

No modo `pull` o export NBD publicado na origem é **obrigatoriamente somente leitura**
(`writable=false` no `block-export-add`, `-r` no `qemu-nbd`). Isto não é endurecimento
opcional: P1 admite uma única escrita na origem, que é metadado de dirty bitmap. Um export
gravável seria violação por desenho, não por falha. Testes de integração devem provar que
uma escrita pelo export é recusada.

### Seed offline não é otimização

Estimativas de referência para a carga inicial. **São duas escalas diferentes e não devem
ser lidas como uma faixa:**

- **11,83 TiB** é o laboratório da 4EDGE, medido em 2026-09-23 nos três nós
  ([censo](../validacao/2026-09-23-censo-do-parque.md));
- **40 TB** é a ordem de grandeza do **cliente-alvo**, cuja distribuição ainda é
  desconhecida — medição M2 do [ADR-0012](0012-resposta-a-perda-de-bitmap.md).

| Link | 11,83 TiB (laboratório, medido) | 40 TB (cliente, estimado) |
|---|---|---|
| 1 Gbps a 100% (irreal) | ~1,2 dia | ~4 dias |
| 1 Gbps realista (~40%) | ~3 dias | ~10 dias |
| 200 Mbps | ~5,5 dias | ~19 dias |

A coluna do laboratório é tamanho medido com vazão arbitrada; a do cliente é tamanho
estimado com vazão arbitrada. Nenhuma das duas vira promessa antes da M1 do ADR-0012, que
é a vazão real de seed entre os datacenters.

Nenhum dos tempos é aceitável para onboarding. O bitmap não sabe como o seed chegou ao destino, então
mídia física seguida do primeiro ciclo incremental é suportada pelo mecanismo sem uma linha
de código a mais.

## Relação com decisões anteriores

**[ADR-0002](0002-espelho-como-volume-cinder.md)** descartou "relay por aplicação externa — destrói o RTO e dobra a banda". Os
modos `jump-ssh` e `rendezvous-wg` **não** são aquilo, e a diferença precisa estar escrita:
o relé descartado no ADR-0002 termina o protocolo e reprocessa o dado; os relés deste ADR
encaminham bytes cifrados sem interpretá-los, e não participam do failover — o espelho já
está no DC-2 quando o desastre acontece, então o relé não entra no caminho do RTO. Ver
[ADR-0009](0009-separacao-rele-control-plane.md).

**`docs/00-visao.md`** afirmava em absoluto que o plano de dados viaja direto do
hypervisor para a receptora. Com este ADR isso passa a valer **por padrão**, com
`jump-ssh` e `rendezvous-wg` nomeados como exceções. O documento de visão foi ajustado
junto com a entrada deste ADR.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| VPNaaS de projeto (Neutron) | Liga sub-redes de tenant e não alcança o hypervisor; incluir a rede de gerência exigiria que ela estivesse plugada no router Neutron, o que não é o caso. Testado e reprovado no laboratório |
| `jump-ssh` como padrão de dados | Considerada e revertida: atraente pela universalidade, mas o comportamento sob perda em transferências longas a desqualifica como padrão |
| WireGuard no hypervisor | Altera rota e carrega módulo de kernel num host de cluster suportado pelo fornecedor. Quando `rendezvous-wg` for necessário, o WireGuard fica em VM de borda, com rota estática no hypervisor |
| Túnel sem TLS do NBD, confiando no túnel | Num hub-and-spoke o hub decifra e recifra; sem TLS do NBD por dentro, o operador do hub vê o tráfego |

## Consequências

- O onboarding de site tem uma etapa de detecção de caminho que grava o modo. Não há
  descoberta automática em tempo de execução.
- O agente precisa de uma abstração de destino (`host`, `porta`, `credencial TLS`) que não
  saiba qual modo está por baixo. Trocar de modo é reconfiguração, não recompilação.
- `jump-ssh` carrega TCP dentro de TCP. Em link com perda o throughput desaba em vez de
  degradar, e num seed de dias qualquer perda compõe. Por isso é fallback, não padrão.
- Um stream TCP não enche cano de alta latência × alta banda, em qualquer modo. Vazão vem
  de paralelismo entre VMs. Medir com uma VM e extrapolar linearmente leva a erro.
- O floating IP do destino é **por par de sites**, criado no onboarding — não por VM
  protegida.
- `deploy/README.md` descrevia um túnel WireGuard ponto a ponto entre datacenters, o que
  contradiz este ADR. Foi reescrito junto com a entrada dele: o padrão é `push` com TLS
  mútuo e sem túnel.
