# ADR-0010: Receptor e armazenamento do espelho

**Data:** 2026-09-23
**Status:** aceito

## Contexto

Este ADR **confirma e estende** o [ADR-0002](0002-espelho-como-volume-cinder.md) no ponto do armazenamento —
espelho em volume Cinder, ponto de recuperação como snapshot Cinder — e decide duas coisas
que ele não decidiu: qual processo serve o destino, e como as receptoras escalam.

O destino precisa de um **processo** que aceite a conexão NBD e escreva os blocos, e de um
**lugar** onde o espelho viva junto dos pontos de recuperação.

O laboratório usa `qemu-nbd` sobre um volume Cinder anexado a uma VM receptora. Isso prova
o mecanismo mas não é desenho de produto: `qemu-nbd` fixa o conjunto de exports no momento
em que sobe, e um processo por disco exportado significa um PID, uma porta e uma config de
TLS por disco.

## Decisão

### Receptor: `qemu-storage-daemon`, controlado por QMP

O receptor é **um** `qemu-storage-daemon` por VM receptora, com um servidor NBD, uma
credencial TLS e um `authz`. Os discos entram e saem em tempo de execução por QMP:
`blockdev-add` para o dispositivo, `block-export-add` para publicá-lo, `block-export-del`
para retirá-lo.

Isso vale pelo mesmo motivo que vale no hypervisor: **é o mesmo protocolo que o agente já
fala.** Uma biblioteca de cliente QMP, dois usos. Proteger um disco novo não reinicia nada,
não toca o fluxo de nenhum outro tenant e não deixa processo órfão para colher depois.

O laboratório continua com `qemu-nbd` — é mais simples de depurar com um disco só. A troca
é de implementação do receptor, não de interface: a control plane pede "publique o volume X
como export Y" nos dois casos.

Disponibilidade confirmada: `qemu-storage-daemon` vem no pacote `qemu-utils` da imagem
Ubuntu usada na validação de 2026-09-23.

### Espelho: volume Cinder; ponto de recuperação: snapshot Cinder

Confirma o [ADR-0002](0002-espelho-como-volume-cinder.md). O que este ADR acrescenta é a mecânica:

- **Espelho = volume Cinder**, sempre atual, alvo direto do `blockdev-backup`.
- **Ponto de recuperação = snapshot Cinder** desse volume, tirado **entre ciclos**, quando
  nenhuma escrita está em voo. Snapshot de volume anexado exige `--force`; a consistência
  vem do agendamento, não da flag.
- **Failover para agora** = criar VM a partir do volume. Segundos, zero conversão.
- **Failover para o passado** = `create volume from snapshot` + boot.
- **Test-failover** = idem, em rede isolada. É o recurso mais usado no dia a dia e sai de
  graça.
- **Retenção** = apagar snapshot pela API.

Nada de sistema de arquivos na receptora, nenhuma cadeia qcow2 para gerenciar, nenhum
`qemu-img` no caminho crítico do desastre. O COW fica no Virtuozzo Storage.

### Ponto de recuperação é da VM, não do volume

O snapshot é por volume, mas o **ponto de recuperação é por VM**, como o [ADR-0002](0002-espelho-como-volume-cinder.md)
já estabelecia. P5 exige:

1. Uma VM de vários discos só ganha ponto de recuperação quando **todos** os seus volumes
   concluíram o **mesmo** ciclo. Não existe ponto parcial válido.
2. Se qualquer volume do conjunto falhar, o conjunto inteiro de snapshots daquele ciclo é
   **descartado**, inclusive os que tinham concluído. Snapshot solto não vira ponto.
3. O registro do ponto de recuperação nomeia o conjunto e o ciclo que o originou, e carrega
   a marca de consistência (aplicação, se houve quiesce; crash, caso contrário).

A atomicidade da leitura na origem já vem do checkpoint único cobrindo todos os discos
(dr-001). Esta decisão é a contrapartida no destino: atomicidade da **publicação**.

### Pool de receptoras

O driver libvirt do Nova limita **discos totais por instância, incluindo o disco raiz** — 26
por padrão, ajustável em `[compute] max_disk_devices_to_attach`. Uma receptora comporta,
portanto, cerca de 25 espelhos.

A control plane mantém um **pool de receptoras com contabilidade de capacidade** e coloca
cada espelho novo numa receptora com vaga, criando outra quando o pool enche. Colocação é
responsabilidade da control plane, não do operador.

Os volumes de uma mesma VM protegida ficam **na mesma receptora**, para que o conjunto de
snapshots de um ciclo seja tirado sob um único ponto de controle.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Um `qemu-nbd` por disco | Conjunto de exports fixo no start, um PID/porta/TLS por disco, processos órfãos após queda. Mantida apenas no laboratório |
| Espelhos como arquivos qcow2 num volume grande | Resolve o limite de anexação e dá snapshot barato, mas empurra uma conversão de TBs para o momento do desastre — troca capacidade por RTO na pior hora possível. Fica registrada como candidata a um **tier de RTO relaxado**, se houver demanda |
| Journal próprio de deltas, ao estilo Zerto | Dá RPO quase contínuo e granularidade por segundo, mas é reimplementar o que o Cinder já entrega com snapshot, e o alvo declarado é RPO de 1 a 4 horas |

## Consequências

- O receptor vira um serviço com ciclo de vida e supervisão, não um comando solto. Precisa
  de reconciliação no boot: ler do banco quais exports deveriam existir e recriá-los.
- O socket QMP do `qemu-storage-daemon` é acesso de escrita a todos os espelhos daquela
  receptora. Vive em socket unix com permissão restrita, nunca em TCP.
- Snapshots Cinder consomem quota e, em backend COW, cadeias longas degradam. A retenção é
  política por tier (ex.: 24 horárias + 7 diárias), definida com a comercial e dimensionada
  antes de virar promessa em contrato.
- O descarte de conjunto parcial precisa ser idempotente e retomável: uma falha durante o
  próprio descarte não pode deixar snapshot órfão sem dono.
- A contabilidade de capacidade do pool tem que considerar o disco raiz da receptora no
  limite de 26, e manter juntos os volumes de uma mesma VM.
- O tamanho do volume espelho é lido do volume de origem e nunca pode ser menor.

## Referências

- [QEMU Storage Daemon](https://www.qemu.org/docs/master/tools/qemu-storage-daemon.html)
- [Accessing QEMU storage features without a VM — LWN](https://lwn.net/Articles/911281/)
- [Configure maximum number of volumes to attach — Nova Specs](https://specs.openstack.org/openstack/nova-specs/specs/stein/implemented/conf-max-attach-volumes.html)
- [Zerto Virtual Replication Journal Overview](https://s3.amazonaws.com/zertodownload_docs/6.0_Latest/Zerto%20Virtual%20Replication%20Journal%20Overview.pdf)
