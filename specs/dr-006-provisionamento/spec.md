# dr-006 — Provisionamento: proteger uma VM é um clique

**Status:** rascunho · **Marco:** M3
**Depende de:** dr-001 (domínio e ciclo), dr-002 (descoberta de discos e bitmaps),
core-002 (conexões)
**Decisões:** [ADR-0008](../../docs/adr/0008-modos-de-transporte.md),
[ADR-0009](../../docs/adr/0009-separacao-rele-control-plane.md),
[ADR-0010](../../docs/adr/0010-receptor-e-armazenamento-do-espelho.md),
[ADR-0011](../../docs/adr/0011-imagem-e-bootstrap-do-receptor.md)

> **Nota de escopo.** Esta spec ocupa a posição que o `specs/README.md` reservava para
> "dr-006 — Receptor: volumes e export", ampliando-a da mecânica do destino para o fluxo
> completo de proteger uma VM. A descoberta dos discos e bitmaps da origem continua sendo
> `dr-002` e entra aqui como dependência, não como conteúdo.

## Por que

No laboratório, proteger uma VM exigiu oito passos manuais: criar volume no destino com o
tamanho certo, anexá-lo à receptora, descobrir o device, gerar certificados, subir o
export, editar o script do agente, disparar o seed, conferir. Cada um com uma forma de
errar em silêncio.

Um produto de DR não pode pedir isso. O operador seleciona a VM e clica em "Proteger".
Tudo o que está acima é consequência.

## Escopo

**Dentro:** provisionamento do destino para uma VM protegida, registro no catálogo,
disparo do seed, entrada no ciclo.

**Fora:** onboarding de site (par de datacenters, credenciais, modo de transporte, relé,
CA, receptora — é `core-002` mais o ADR-0011); descoberta dos discos da origem (`dr-002`);
failover, test-failover e failback.

## Fronteira: o que a plataforma faz e o que continua humano

Automático, por VM:

| Passo | Como |
|---|---|
| Ler a origem | via `dr-002`: flavor, volumes e tamanhos, portas, IPs, security groups, ordem de boot |
| Criar o volume espelho | Cinder `POST /volumes`, tamanho lido da origem, no projeto do par de sites |
| Anexar na receptora | Nova `POST /servers/{id}/os-volume_attachments`, receptora escolhida pelo pool |
| Achar o device | Serial: `/dev/disk/by-id/virtio-<prefixo-do-volume-id>` — nunca `lsblk` por ordem |
| Publicar o export | QMP no receptor: `blockdev-add` + `block-export-add`, nome determinístico |
| Disparar o seed | Agente do hypervisor: checkpoint + `blockdev-backup` full, com throttle |
| Entrar no ciclo | Agendador, na frequência do RPO daquela VM |

Humano, e só no onboarding do cliente:

- entrega da conta de serviço dos dois clusters;
- liberação no firewall de perímetro do DC, quando houver além do security group.

Floating IP e security group são **por par de sites**, criados no onboarding. Proteger a VM
número 40 não toca em rede nenhuma.

## Requisitos

**R1 — Idempotência.** Repetir "Proteger" para a mesma VM não cria recurso duplicado.

**R2 — Retomabilidade.** Um provisionamento interrompido em qualquer passo é retomado do
ponto onde parou. O retry nunca cria um segundo volume.

**R3 — Reconciliação, não recriação.** Todo recurso criado tem nome determinístico derivado
de `(tenant_id, vm_id, disco)`. Antes de criar, a plataforma procura. Se existe e confere,
adota. Se existe e diverge, para e reporta — nunca "conserta" sozinho.

**R4 — Tamanho.** O volume espelho tem o tamanho do volume de origem. Nunca menor. Origem
que cresceu depois de protegida é divergência, tratada como R3.

**R5 — Colocação.** A receptora sai do pool com contabilidade de capacidade, respeitando o
limite de discos por instância do Nova, disco raiz incluído. Todos os volumes de uma mesma
VM protegida ficam na **mesma** receptora (ADR-0010).

**R6 — Rollback parcial.** Falha no meio deixa o sistema num estado nomeado e consultável,
nunca em recursos órfãos sem dono. Todo recurso criado é registrado **antes** de ser criado.

**R7 — Tenant.** Toda linha gravada carrega `tenant_id`. Todo recurso criado no destino vai
para o projeto do par de sites daquele tenant.

**R8 — Nada destrutivo.** O provisionamento cria. Não apaga volume, snapshot, checkpoint ou
bitmap. Remoção de proteção é fluxo separado, com confirmação humana explícita (P6).

**R9 — Conjunto de discos é atômico.** Uma VM de vários discos só entra em `protegida`
quando todos os seus volumes concluíram o mesmo ciclo. Conjunto parcial não vira ponto de
recuperação e é descartado inteiro (ADR-0010, P5).

## Estados

```
pendente → provisionando → semeando → protegida
                ↓              ↓          ↓
             falhada       falhada    degradada
```

- `provisionando` — criando volume, anexando, publicando export
- `semeando` — seed em andamento
- `protegida` — ciclo ativo dentro do RPO
- `degradada` — ciclo ativo mas fora do RPO, ou último ciclo falhou
- `falhada` — provisionamento parou; estado consultável, retomável

## Critérios de aceite

1. Proteger uma VM de um disco cria exatamente um volume no projeto certo, do tamanho
   exato, anexado e exportado, e o seed conclui.
2. Repetir a operação não cria segundo volume nem segundo export.
3. Matar o processo durante a anexação e retomar conclui sem recurso órfão.
4. Uma VM de vários discos vira um conjunto de volumes na mesma receptora, com o mesmo
   `tenant_id`, e o checkpoint que inicia o seed cobre todos os discos numa transação
   (dr-001).
5. Falha num volume de um conjunto descarta o conjunto inteiro daquele ciclo, incluindo os
   volumes que haviam concluído.
6. Volume de origem maior que o espelho existente é reportado como divergência, sem escrita.
7. Operador de um tenant não vê nem alcança recurso de outro (core-001).
8. Nenhum caminho deste fluxo emite comando de remoção.

## Em aberto

- **Origem `raw`.** Volumes `raw` não suportam checkpoint ("checkpoint for disk vda
  unsupported for storage type raw"). O censo mostrou incidência baixa. Proposta: recusar
  com mensagem clara e marcar a VM como não-protegível. Confirmar em `/speckit.clarify`.
- **Guest agent ausente.** Metade do parque não tem agente ativo, o que significa
  consistência de crash em vez de consistência de aplicação. Flag por VM, e o ponto de
  recuperação carrega a marca.
- **Sobrevivência do bitmap à migração automática do VHI.** Se o bitmap não sobreviver, o
  agente precisa detectar e reagendar resync — o que muda o estado `degradada`. É o único
  item em aberto que pode alterar o desenho do agente.
