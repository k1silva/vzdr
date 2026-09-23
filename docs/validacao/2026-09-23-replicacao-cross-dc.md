# Validação — replicação cross-datacenter com TLS mútuo

**Data:** 2026-09-23 · **Origem:** DC-1, nó `vhi-hv02` · **Destino:** DC-2, VM `receptor`

Registro do primeiro ciclo de replicação entre datacenters. Complementa a validação
local de 18/09 e fecha o modo `push` do [ADR-0008](../adr/0008-modos-de-transporte.md).

## Resultado

| Medição | Valor |
|---|---|
| Disco de origem | `instance-000002ac`, vda qcow2, 68.719.476.736 bytes (64 GiB) |
| Seed (`sync: full`) | **5.535,6 MiB** — só o alocado, de 64 GiB nominais |
| Ciclo incremental, janela de 24min08s | **2,8 MiB — 0,05% do seed** |
| Taxa de mudança extrapolada | ~170 MiB/dia para esta VM |
| Integridade do espelho | GPT íntegro: BIOS boot 1M, `/boot` 2G, raiz 62G |
| Impacto na VM protegida | nenhum — ligada, sem agente no guest, sem pausa |

Checkpoints: `dr-20260923-163112` (seed) → `dr-20260923-165520` (ciclo).

Num RPO de 1 hora, essa VM moveria ~7 MiB por ciclo entre datacenters.

## Transporte validado

Modo `push`: o QEMU do hypervisor de origem disca para o floating IP do destino. O
cliente é o processo QEMU, não a VM protegida e não a control plane.

- **Um único IP público**, no destino. A origem só precisa de saída NAT.
- **TLS mútuo** com `verify-peer=on` nas duas pontas e `authz-simple` restringindo o CN
  do cliente. Firewall por `/32` como segunda camada.
- Confirmado por `nbdinfo`: `newstyle-fixed with TLS`, com `can_multi_conn`, `can_trim`
  e `base:allocation`.

### Destino

```bash
qemu-nbd \
  --object tls-creds-x509,id=tls0,endpoint=server,dir=/etc/pki/qemu,verify-peer=on \
  --object authz-simple,id=authz0,identity=CN=<cn-do-cliente> \
  --tls-creds tls0 --tls-authz authz0 \
  --format=raw --persistent --shared=8 --cache=none --aio=native \
  -b 0.0.0.0 -p 10809 -x <nome-do-export> /dev/vdb
```

### Origem

```python
qs("object-add", {"qom-type":"tls-creds-x509","id":"tls0",
                  "dir":"/etc/pki/qemu","endpoint":"client","verify-peer":True})
q("blockdev-add", {"node-name":"t1","driver":"nbd",
                   "server":{"type":"inet","host":H,"port":P},
                   "export":E,"tls-creds":"tls0","tls-hostname":H})
```

`object-add` é idempotente por necessidade: o objeto `tls0` sobrevive no processo QEMU
entre execuções, então a segunda chamada erra. O agente precisa tolerar isso.

## Pegadinhas descobertas hoje

1. **VPNaaS de projeto não serve.** Liga sub-redes de tenant; o hypervisor não está nelas.
   Testado e reprovado — foi o que motivou o modo `push` do ADR-0008.
2. **O QEMU não roda como root.** `/etc/pki/qemu` precisa ser legível pelo usuário do
   processo (`qemu` neste parque). Sem isso o erro vem como "cannot load certificate" e
   parece problema de certificado.
3. **`extendedKeyUsage` importa.** Certificado de cliente assinado com `serverAuth` é
   recusado pelo GnuTLS. Cliente é `clientAuth`, servidor é `serverAuth`.
4. **`subjectAltName` com o IP é obrigatório** no certificado do servidor. Sem ele o
   cliente recusa a identidade, e o erro não se parece com o que é.
5. **`nbdinfo` antigo não tem `--tls`.** Usa URI: `nbds://host:port/export?tls-certificates=DIR`.
   Melhor ainda: testar com `qemu-img info --object tls-creds-x509,...` mais um
   `json:{...}` — é o mesmo cliente que o `blockdev-backup` usa.
6. **Nunca ative LVM do espelho no receptor.** Ubuntu de origem e receptor têm ambos
   `ubuntu-vg`. Ler a tabela de partições (`fdisk -l`) prova o que precisa ser provado.

## O que isto fecha e o que continua aberto

**Fecha:** viabilidade do mecanismo cross-DC, o modo `push` como padrão do plano de
dados, e a confirmação de que `qemu-storage-daemon` existe no receptor (pacote
`qemu-utils`), pendência do [ADR-0010](../adr/0010-receptor-e-armazenamento-do-espelho.md).

**Continua aberto:**

- **Sobrevivência do bitmap à migração automática do VHI.** Único item que ainda pode
  alterar o desenho do agente. Exige cluster com mais de um nó.
- Censo nos demais nós do DC-1, para transformar "40 TB nominais" no número real.
- Medição agregada de taxa de mudança do parque, que dimensiona o RPO contratável.
- Retenção e capacidade no DC-2, decisão com a comercial.
