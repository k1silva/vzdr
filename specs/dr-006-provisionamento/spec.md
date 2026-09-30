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

**Fora:** onboarding de site — a **conexão** com cada cluster é `core-002`; o **par de
sites** (modo de transporte, relé, CA, floating IP, receptora, orçamento de banda) é
`dr-012`. Também fora: descoberta dos discos da origem (`dr-002`); failover,
test-failover e failback.

Em M3 o par de sites é preparado à mão, como o laboratório fez; a `dr-012` automatiza isso
em M4. Esta spec pressupõe o par pronto, não importa como.

## Fronteira: o que a plataforma faz e o que continua humano

Automático, por VM:

| Passo | Como |
|---|---|
| Ler a origem | via `dr-002`: flavor, volumes e tamanhos, portas, IPs, security groups, ordem de boot |
| Criar o volume espelho | Cinder `POST /volumes`, tamanho lido da origem, no projeto do par de sites |
| Anexar na receptora | Nova `POST /servers/{id}/os-volume_attachments`, receptora escolhida pelo pool |
| Achar o device | Serial: `/dev/disk/by-id/virtio-<prefixo-do-volume-id>` — nunca `lsblk` por ordem |
| Anexar o nó no daemon | QMP no receptor: `blockdev-add`. **Durável**, nome de R3 — é a anexação vista de dentro do `qemu-storage-daemon` |
| Publicar o export | QMP no receptor: `block-export-add`. **Por ciclo e por disco**, nome derivado dos dois. Pedido pela [`dr-001`](../dr-001-dominio-ciclo/spec.md) como `PublicarExport`, não por este fluxo |
| **Derrubar o export para cercar** | QMP no receptor: `block-export-del` com `mode: hard`. Pedido pela [`dr-001`](../dr-001-dominio-ciclo/spec.md) quando um agente fica inalcançável com job escrevendo — ver "Cercar o escritor zumbi" |
| Disparar o seed | Agente do hypervisor: checkpoint + `blockdev-backup` full, com throttle |
| Entrar no ciclo | Agendador, na frequência do RPO daquela VM |

### Cercar o escritor zumbi

A [`dr-001`](../dr-001-dominio-ciclo/spec.md) decide **quando** cercar; a mecânica é desta
spec, porque quem é dono do ciclo de vida do export é quem sabe derrubá-lo.

O caso: agente da origem inalcançável com `blockdev-backup` ainda escrevendo. Lease vencido
não prova que o job parou — prova que o reporte parou. Em vez de esperar evidência que pode
não vir, tira-se do zumbi a possibilidade de continuar: `block-export-del` com `mode: hard`
desconecta cliente ativo, e o job morre por perder a conexão.

Isso é possível porque a receptora é nosso software e mantém **túnel de saída próprio** para
o relé ([ADR-0009](../../docs/adr/0009-separacao-rele-control-plane.md), com a chave do
[ADR-0011](../../docs/adr/0011-imagem-e-bootstrap-do-receptor.md)): ela está alcançável
exatamente no cenário em que o agente da origem não está.

**Compatibilidade, e o fallback.** O `mode: hard` depende da versão de `qemu-utils` que o
repositório do cliente serve. O ADR-0011 já obriga o onboarding a registrar a versão
encontrada e rodar a suíte de compatibilidade contra ela; **esta linha entra nessa suíte**.
Sem `mode: hard`, o cercamento vira reinício do `qemu-storage-daemon` daquela receptora —
mais grosseiro, mesmo efeito, e derruba os exports dos outros discos da mesma receptora
junto, que voltam no ciclo seguinte.

Cercar **não** causa resync completo: `bitmap-mode: on-success` garante que o job abortado
não limpou bitmap, então o ciclo seguinte recopia a janela inteira por cima das escritas
parciais.

Humano, e só no onboarding do cliente:

- entrega da conta de serviço dos dois clusters;
- liberação no firewall de perímetro do DC, quando houver além do security group.

Floating IP e security group são **por par de sites**, criados no onboarding. Proteger a VM
número 40 não toca em rede nenhuma.

## Requisitos

**R1 — Idempotência.** Repetir "Proteger" para a mesma VM não cria recurso duplicado.

**R1b — Config drive não é dado de cliente.** Discos `raw` são excluídos da replicação
**por desenho**, não por limitação do mecanismo. O censo de 2026-09-23 mediu: os 24 discos
`raw` do parque somam 1,5 GiB, têm 0,06 GiB cada, estão todos no target `sda` e são config
drives gerados pelo Nova — no failover o catálogo recria a VM e o Nova gera um novo. Os 115
discos de dado são qcow2 e suportam checkpoint, então o escopo do mecanismo é o parque
inteiro. Ver [censo](../../docs/validacao/2026-09-23-censo-do-parque.md).

Um disco `raw` que **não** seja config drive é divergência, tratada como R3: para e
reporta, em vez de replicar pela metade ou excluir em silêncio.

**R2 — Retomabilidade.** Um provisionamento interrompido em qualquer passo é retomado do
ponto onde parou. O retry nunca cria um segundo volume.

**R3 — Reconciliação, não recriação.** Todo recurso **durável** — volume espelho, anexação —
tem nome determinístico derivado de `(tenant_id, vm_id, disco)`. Antes de criar, a
plataforma procura. Se existe e confere, adota. Se existe e diverge, para e reporta — nunca
"conserta" sozinho.

**O export é a exceção, e não por conveniência.** Ele é por ciclo, e seu nome deriva do
ciclo **e do disco** — a regra de identidade da
[`dr-001`](../dr-001-dominio-ciclo/spec.md). O disco é necessário por causa do R5 abaixo:
todos os discos de uma VM ficam na mesma receptora, e o servidor NBD dela não aceita dois
exports com o mesmo nome. Repare que `blockdev-add` e `block-export-add`
estavam num passo só e **nunca tiveram o mesmo tempo de vida**: o nó é a anexação vista de
dentro do daemon e dura o que ela dura; o export é o nome exposto na rede. O
`block-export-del`, inclusive com `mode: hard`, remove o export e **deixa o nó** — o volume
segue anexado e o ciclo seguinte republica. O motivo é o cercamento: `block-export-del`
derruba um export por nome, e com nome fixo por disco um cercamento atrasado mataria o job
do ciclo seguinte em vez do zumbi. Cercar tem que identificar a **instância**, não o disco.
Consequência prática: não há export para adotar na retomada; há export órfão para limpar,
definido como export cujo ciclo não está ativo.

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

**R9 — Conjunto de discos é atômico.** Uma VM de vários discos só ganha ponto de
recuperação quando todos os seus volumes concluíram o mesmo ciclo. Conjunto parcial não vira ponto de
recuperação e é descartado inteiro (ADR-0010, P5).

**R10 — Orçamento de banda é do par de sites, não do job.** O seed disparado aqui entra
no orçamento vigente do par e é reajustado quando a janela vira, sem recomeçar
(ADR-0013). **Não existe percentual por job:** cinco jobs a 20% cada saturam o enlace
enquanto cada um se comporta "educadamente". O agente divide o orçamento do par entre os
jobs ativos e aplica com `block-job-set-speed`; job que entra ou sai redivide o restante.

Um seed é o job mais pesado que este fluxo cria, então disparar proteção em massa no meio
do expediente é exatamente o caso que a regra existe para conter.

## Estados

```
pendente → provisionando → semeando → em_protecao
                ↓              ↓
             falhada        falhada
```

- `provisionando` — criando volume, anexando, publicando export
- `semeando` — seed em andamento
- `em_protecao` — seed concluído, VM no ciclo. Diz onde a VM está no **ciclo de vida**, e
  não se a proteção está em dia
- `falhada` — provisionamento parou; estado consultável, retomável

**Ciclo de vida é marcado; saúde é derivada.** Estes são estados de processo, e mudam
quando algo acontece. Se a proteção está em dia ou `degradada` não é estado desta máquina:
é conta sobre a idade do ponto de recuperação, e é definida uma vez, na
[`dr-001`](../dr-001-dominio-ciclo/spec.md).

Esta seção já teve `protegida` e `degradada` como estados, com o limiar "fora do RPO, ou
último ciclo falhou". Isso contradizia a `dr-001`, que degrada a 2× o RPO, por tempo e não
por tentativas. A contradição foi resolvida por regra, e não escolhendo um vencedor: o
próximo conceito que aparecer nos dois lugares tem critério para ser arbitrado.

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

- **Guest agent ausente.** Metade do parque não tem agente ativo, o que significa
  consistência de crash em vez de consistência de aplicação. Flag por VM, e o ponto de
  recuperação carrega a marca.
- **Sobrevivência do bitmap à migração automática do VHI.** Se o bitmap não sobreviver, o
  agente precisa detectar e reagendar resync — o que afeta a saúde da proteção, calculada
  na [`dr-001`](../dr-001-dominio-ciclo/spec.md). É o único
  item em aberto que pode alterar o desenho do agente.
