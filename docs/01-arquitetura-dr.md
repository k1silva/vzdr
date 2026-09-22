# Arquitetura do DR

## Topologia

```
DC-1 (origem)                                  DC-2 (destino)
  hypervisor
  └─ VM protegida
       checkpoint + dirty bitmap  ──blocos sujos──▶  volume Cinder espelho
       blockdev-backup              WAN/TLS           + snapshot = ponto de recuperação
```

O espelho **é um volume Cinder**, não um arquivo. Essa escolha separa minutos de horas no
failover: no desastre, basta desanexar da receptora e criar a VM.

## O ciclo

1. **Checkpoint** cobrindo todos os discos da VM de uma vez:
   `virsh checkpoint-create-as <dom> --name dr-N --diskspec vda,checkpoint=bitmap --diskspec vdb,...`
2. **Congelar o ponto-no-tempo** — transação QMP atômica que cria um bitmap temporário
   desabilitado e mergeia nele a janela pendente. Sem isso, o mapa muda durante a cópia.
3. **Conectar o destino** — `blockdev-add` de um nó NBD remoto, com `tls-creds`.
4. **Copiar** — `blockdev-backup` com `sync: incremental`, `bitmap: <temporário>`,
   `bitmap-mode: on-success`, `speed: <throttle>`.
5. **Commit ou descarte** — sucesso: snapshot Cinder, remove temporário, apaga checkpoint
   anterior. Falha: descarta só o temporário; a janela continua intacta.

## Validado no cluster

| Medição | Resultado |
| --- | --- |
| Carga inicial, volume de 80 GiB | 8,7 GiB — só o alocado |
| Ciclo incremental após ~4 min | 16,7 MiB — 0,19% |
| Integridade do espelho | GPT, partições e LVM reconhecidos no destino |

Ambiente: libvirt 9.5.0, QEMU 8.2.0, `<backup supported='yes'/>`, bitmaps persistentes com
granularidade de 64 KiB.

## Pegadinhas descobertas na validação

1. **Nunca ligar VM por `virsh`** num cluster gerenciado pelo Nova — o nova-compute detecta
   a divergência de power state e mata a VM. Ciclo de vida sai pela API.
2. **Volumes `raw` não suportam checkpoint.** Erro: *"checkpoint for disk vda unsupported
   for storage type raw"*. No parque medido, só um volume raw, e vazio.
3. **`bitmap-mode` tem que ser `on-success`** com `sync: incremental`. O QEMU 8.2 rejeita
   `never`. Como o bitmap usado é temporário, isso não afeta os checkpoints reais.
4. **`checkpoint-create-as --quiesce` não existe neste fork** (flag 0x2 rejeitada). A
   consistência de aplicação sai de `domfsfreeze`/`domfsthaw` manuais, com watchdog.
5. **`qemu-img info` falha em volume de VM ligada** (lock do QEMU). Use `-U`, ou pegue o
   tamanho por QMP com `query-block`.
6. **node-name é efêmero** (`libvirt-1-format` muda a cada boot). Resolver a cada ciclo.
7. **Não validar espelho no hypervisor** — colisão de nome de VG entre guests e risco de
   ativar volume de cliente no host. Valide em máquina dedicada.
8. **Nunca bootar um espelho com rede ligada** — mesmo IP e hostname da VM de produção.

## API proprietária da Virtuozzo

O fork removeu o `backup-begin` upstream e colocou `x-block-snapshot-create`,
`x-block-export-start` e `x-block-checkpoint-remove`. O `qemu.conf` mostra que esse export
tem TLS mútuo nativo e faixa de portas autoalocada (`blockexport_tls_x509_*`,
`nbd_export_port_min = 49300`), hoje desligado.

O parser já aceitou `<domainblockexport type="nbd">` e pede um elemento `<address>`.
Decifrar isso pode simplificar o agente — mas é otimização, não dependência. O desenho
funciona só com QMP padrão, que já foi validado.
