# ADR-0002: O espelho é um volume Cinder, não um arquivo

**Data:** 2026-09-22
**Status:** aceito

## Contexto

O destino da replicação precisa receber escrita em bloco. A validação em laboratório usou
um arquivo `mirror.qcow2` exportado por `qemu-nbd`, o que funcionou.

Mas o objetivo do produto é RTO curto: a VM no ar no DC-2 em minutos.

## Decisão

Cada volume protegido tem, no cluster de destino, um volume Cinder do mesmo tamanho,
anexado a uma VM receptora que o expõe por NBD. Os pontos de recuperação são snapshots
Cinder nativos, agrupados por VM.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Arquivo qcow2 em disco da receptora | No desastre seria preciso converter TB em volume Cinder antes de bootar — horas de RTO |
| Objeto em bucket S3 | Object storage não tem escrita aleatória; restauração leva horas ou dias |
| Relay por aplicação externa | Destrói o RTO e dobra a banda; cada byte atravessaria a internet duas vezes |
| iSCSI direto do hypervisor de origem | Frágil sobre WAN e provavelmente barrado pelo driver do VHI |

## Consequências

Fica mais fácil: failover é operação de metadado — desanexar e criar a VM. Segundos por VM,
independente do tamanho do disco. Os snapshots aparecem no painel do VHI.

Fica mais difícil: exige VM receptora no destino e gestão de um pool delas. O teto do Nova
é de ~26 volumes por instância, mas o limite que chega primeiro na prática é o IO da
receptora, não a contagem.
