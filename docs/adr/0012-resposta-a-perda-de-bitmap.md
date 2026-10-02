# ADR-0012: Resposta à perda de bitmap

**Data:** 2026-09-23
**Status:** aceito — decisão 1 substituída pelo [ADR-0016](0016-confianca-no-bitmap.md) e decisão 2 rebaixada em 2026-10-02 (ver a emenda no fim)

> **Leia antes de implementar: este ADR não fecha tudo.** A decisão 1 é invariante de
> segurança e vale desde já. A **decisão 3 — resync diferencial — está em análise**, não
> decidida, e depende das medições M1–M4 em "O que falta medir"; o rastreio delas está em
> [`docs/pendencias.md`](../pendencias.md). O status é `aceito` porque o que este
> documento fecha, fecha — não porque tudo esteja resolvido.
>
> A forma ortodoxa seria separar a decisão 3 num ADR próprio com status `proposto`. Está
> registrada como candidata em `docs/pendencias.md`.

> **Escopo dos números.** O censo abaixo é do **laboratório da 4EDGE**: 11,83 TiB, três
> nós, 65 VMs. O ambiente do **cliente-alvo é de 40 TB** e sua distribuição é desconhecida.
> Nenhuma priorização neste ADR pode se apoiar na distribuição do laboratório como se fosse
> a do cliente. Onde isso acontecia, virou pergunta em aberto.

## Contexto

O ciclo incremental depende de um dirty bitmap mantido pelo QEMU que executa a VM. O
bitmap vive no processo. Três eventos podem invalidá-lo: migração ao vivo, failover de HA
e queda do host.

**Medido no laboratório (2026-09-23):** a capability `dirty-bitmaps` do QEMU está com
`state: false` por padrão neste parque. Não é conclusivo — o libvirt pode ligá-la ao
iniciar a migração —, mas o padrão desligado basta para tratar bitmap pós-migração como
não-confiável até prova em contrário. Há chamado aberto com a Virtuozzo perguntando por
que está desligada e se há forma suportada de ligá-la.

**Queda de host é diferente e não tem volta.** O bitmap só é gravado no qcow2 no
fechamento limpo. Host que morre não fecha limpo: o bitmap fica marcado inconsistente e o
QEMU recusa usá-lo. Não é escolha de arquitetura, é o mecanismo. Depois de HA, incremental
acabou.

### O que o censo mudou

Censo dos três nós, 2026-09-23:

| Nó | VMs | Discos | Alocado |
|---|---|---|---|
| hv01 | 12 | 18 | 3.163,54 GiB |
| hv02 | 24 | 44 | 3.281,71 GiB |
| hv03 | 29 | 53 | 5.664,22 GiB |
| **Total** | **65** | **115** | **12.109 GiB — 11,83 TiB** |

Os 24 discos `raw` somam 1,5 GiB no cluster: são todos config drives de 0,06 GiB,
regenerados pelo Nova no failover e **excluídos da replicação por desenho**, não por
limitação. Os 115 discos de dado são qcow2 e suportam checkpoint.

E a distribuição é um degrau, não uma curva:

| VM | Nó | Alocado |
|---|---|---|
| `instance-0000025d` | hv03 | 3.836 GiB |
| `instance-00000261` | hv01 | 2.835 GiB |
| `instance-00000189` | hv02 | 2.546 GiB |
| | | **9,00 TiB — 76,1% do parque** |

As outras 62 VMs somam 2,82 TiB, média de 47 GiB. A quarta maior tem 607 GiB; depois dela
vêm 266, 220, 190, 175, 154 GiB.

Esse degrau é quem escreve a política abaixo.

## Decisão

### 1. Detecção: o nó é parte do estado do ciclo — **substituída pelo ADR-0016; o que era do executor, rebaixado**

Esta não é uma escolha entre alternativas a serem testadas: é invariante de segurança. Ou o
agente descarta o bitmap após troca de nó, ou pode usar um bitmap inválido e produzir
espelho errado em silêncio. Os testes pendentes dirão **com que frequência** isso ocorre e
**quanto custa** a resposta — não se a regra é necessária.

O agente grava, a cada ciclo, o nó em que o checkpoint foi criado. No ciclo seguinte, se o
nó atual difere do gravado:

1. o bitmap é **descartado sem tentativa de uso** — não se confia em bitmap que sobreviveu
   a evento de host;
2. a VM passa a `DEGRADADA`, motivo `migracao_detectada`;
3. um job de resync é **criado, não iniciado**: ele entra na política de janela, throttle e
   prioridade;
4. enquanto o resync estiver ativo, aquela VM não participa de migração automática, pelo
   mecanismo que o VHI expuser. Se o VHI não expuser nenhum, o resync reinicia e o evento é
   registrado como `resync_interrompido_por_migracao`;
5. `DEGRADADA` tem prazo. Sem progresso por N horas (configurável por VM, com padrão),
   alarme e escalonamento.

**Nunca há cópia grande em silêncio.** Toda transferência acima do volume de um ciclo
normal é um job visível, com motivo, tamanho estimado, progresso e previsão.

A regra 4 fecha um laço real: migração dispara resync, resync longo é interrompido por
nova migração, e a VM nunca volta a `PROTEGIDA`.

**Mecanismo:** o teste de confiança e o gatilho passam ao ADR-0016, e se cumprem por
`dr-001/T9` e `dr-001/T6`; o que era do executor do resync (regras 4 e 5), `C-006`. Até a
T9 e a T6, o código faz a comparação de nó da T5,
`tests/unit/test_ciclo.py::test_migracao_detectada_o_ciclo_nao_executa`.

### 2. `DEGRADADA` não é desprotegida — **rebaixada**

Os pontos de recuperação já existentes no destino permanecem válidos e utilizáveis durante
todo o período degradado. O que para é a criação de pontos **novos** no ritmo prometido: o
ponto mais recente congela e envelhece até o resync terminar.

A interface precisa dizer isso explicitamente, porque a leitura natural de "degradada" é
"desprotegida", e a diferença é o produto inteiro.

**Mecanismo:** `C-005`.

### 3. Resync: completo primeiro, diferencial depois — **em análise**

O resync usa **seed completo**, que já existe. O diferencial fica com o desenho fechado
abaixo e a implementação pendente.

**Só um motivo para essa ordem está estabelecido**, e ele independe de qual parque se
proteja: o passo de hash do diferencial falha em silêncio. Hash errado produz espelho
errado que só aparece no failover. Verificá-lo exige comparação byte a byte contra a
origem, automatizada — o que só existe depois da base funcionar em produção. Construir
antes é construir sem rede de proteção justamente na parte perigosa.

**O que NÃO está estabelecido** é a prioridade relativa — se o diferencial é a próxima
coisa depois da base ou se espera. A tentação foi decidir isso pela distribuição do
laboratório (61 de 65 VMs abaixo de 600 GiB, seed completo cabe na janela). Isso não vale:
o laboratório tem 11,83 TiB, o cliente-alvo tem 40 TB e distribuição desconhecida. Quatro
VMs de 10 TB mudariam a conclusão inteiramente.

Fica em aberto, a decidir com as medições abaixo.

**Mecanismo:** `M1`, `M2`, `M3`, `M4`.

## O diferencial, desenhado

Registrado aqui para não se perder o raciocínio.

**Requisito:** produzir um espelho consistente com **um ponto no tempo definido**, não com
um alvo em movimento, e sem parar a VM.

**Mecanismo — checkpoint antes, correção depois:**

```
1. checkpoint C          → bitmap novo passa a gravar a partir de agora
2. passada de hash       → lê, compara, transfere as divergências
                           (horas; leitura suja é aceitável)
3. ciclo incremental C   → recopia tudo escrito durante o passo 2
4. espelho exato, checkpoint válido para continuar
```

O passo 2 não precisa ser consistente, só chegar perto: qualquer bloco escrito enquanto ele
rodava está marcado no bitmap C, e o passo 3 corrige. O espelho fica consistente com o ponto
do **fim** do processo, que é um ponto de recuperação mais recente do que o do começo.

O passo 3 é o ciclo incremental que já existe.

**Mecânica do passo 2:**

- origem: `block-export-add` com `writable=false` sobre o QEMU que já executa a VM (P1 não
  admite export gravável na origem), cliente libnbd local lendo e hasheando blocos de 4 MiB;
- destino: leitura local do dispositivo de bloco do espelho, mesmos blocos, mesmo hash;
- troca das listas pelo canal de controle — cerca de 21 MB para 2,5 TiB;
- transferência: o cliente lê da origem o bloco divergente e escreve no export do destino;
- `base:allocation` do NBD dispensa hashear região nunca escrita;
- retomada por índice de bloco: a varredura é linear.

**Ganho estimado na `instance-00000189`:**

| | Seed completo | Diferencial |
|---|---|---|
| Rede | 2.546 GiB | ~10–20 GiB |
| Tempo | ~22 h a 50 MiB/s | ~2 h, limitado por leitura |
| Custo | banda WAN | I/O de leitura nos dois lados, com throttle |

**Risco a tratar na implementação:** o passo 2 falha em silêncio. Hash errado produz espelho
errado que só aparece no failover. Exige verificação byte a byte contra a origem num ponto
parado, como critério de aceite.

## O que falta medir

A decisão 3 fecha quando estes quatro números existirem. Nenhum depende de escrever código.

| # | Medição | O que decide |
|---|---|---|
| M1 | **Vazão real de seed entre os datacenters.** O seed validado transferiu 5.535,6 MiB sem cronometragem. Repetir com `time`. | Converte tamanho em horas. Sem ela, toda estimativa de tempo de resync é chute — inclusive as deste documento. |
| M2 | **Distribuição do parque do cliente-alvo.** Mesmo `censo-discos.sh`, rodado lá. | Diz se o diferencial é urgente ou confortável. É a medição que falta para a decisão 3, e ela não está no laboratório. |
| M3 | **Taxa real de mudança**, com bitmap em amostra de 5 a 8 VMs cobrindo os perfis, ao longo de 48h. | Diz quanto o diferencial transferiria de fato — ou seja, qual o ganho real sobre o seed completo. |
| M4 | **Sobrevivência do bitmap à migração automática do VHI.** Exige dois nós e VM descartável. | Se o bitmap sobreviver, a frequência de resync despenca e a decisão 3 perde urgência. Se não sobreviver, ganha. Há chamado aberto com a Virtuozzo sobre a capability `dirty-bitmaps` desligada. |

Enquanto M1–M4 não existirem, os tempos citados neste documento (22 h para 3,75 TiB a
50 MiB/s, ~2 h de diferencial) são **estimativas com vazão arbitrada**, não medições.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Iniciar resync completo imediatamente ao detectar perda de bitmap | Satura o link no meio do expediente e derruba a replicação das demais VMs junto. O job é criado, a política decide quando roda. |
| Overlay (`blockdev-snapshot`) para congelar a leitura da origem | Atende ao requisito de ponto no tempo, mas **este fork bloqueia migração de domínio com snapshot**. Um overlay de horas numa VM de 2,5 TiB a prende ao host, inclusive contra HA e manutenção. Troca resync caro por VM presa. |
| Construir o diferencial antes da base em produção | O passo 2 corrompe em silêncio quando erra. Verificá-lo exige espelho verificável automaticamente, que só existe depois da base funcionando. Construir antes é construir sem rede de proteção justamente na parte perigosa. **Este é o único argumento de ordem que não depende de qual parque se protege.** |
| Decidir a prioridade do diferencial pela distribuição do laboratório | O laboratório tem 11,83 TiB com 76% em três VMs. O cliente-alvo tem 40 TB e distribuição desconhecida. Usar um como proxy do outro é o erro que a revisão deste ADR corrigiu. Depende de M2. |
| Seed offline (mídia física) como resposta a rebalanceamento | Mecanismo de Day 0 e de recuperação planejada. Como rotina de Day 2, disparada por decisão do scheduler, não escala e vira chamado manual. |
| Impedir permanentemente a migração das VMs grandes | Quebra manutenção e HA. A política correta é não participar de **rebalanceamento automático**, mantendo migração administrativa e HA sempre permitidas. |
| Tornar o bitmap persistente à queda de host | Impossível com dirty bitmaps do QEMU: o bitmap só é gravado no fechamento limpo. Host que morre não fecha limpo. |

## Consequências

- O nó de origem vira coluna do estado do ciclo, com histórico. Isso também dá a métrica
  "quantos resyncs foram causados por migração", que é o argumento objetivo para discutir
  placement com o time de infraestrutura.
- Job de resync é entidade de primeira classe: motivo, tamanho, progresso, previsão, e
  política de janela própria.
- Leitura de 2,5 TiB no storage de produção, quando o diferencial existir, precisa de
  throttle e janela. Não é operação invisível.
- O prazo de `DEGRADADA` é parâmetro da ferramenta, por VM, com padrão — não cláusula de
  contrato. Contrato fica para quando houver medição de vazão.
- Falta a vazão real de seed entre os datacenters. Sem ela, a faixa de tamanho que separa
  "seed completo cabe na janela" de "precisa de diferencial" é estimativa.

## Emenda de 2026-10-02: o que estava afirmado sem mecanismo, e para onde foi

O texto acima é o original. Esta emenda acrescenta, e não reescreve: os títulos das decisões
ganharam o marcador do estado em que ficaram, e cada uma, a linha `**Mecanismo:**`. Foi o
que o meta-checador cobrou ao passar a cobrir este documento — as três decisões nasceram
vermelhas, como previsto.

**Decisão 1 — substituída.** Ela usava a comparação de nó como teste de confiança do bitmap,
e isso é procurador que erra nos dois sentidos: nó igual não implica bitmap bom (o ciclo de
energia do guest), nó diferente não implica bitmap ruim (a migração graciosa, P-001). A
evidência está no [ADR-0016](0016-confianca-no-bitmap.md), que passa a decidir o teste e o
gatilho, lendo o estado do próprio bitmap. O que a decisão dizia sobre o **executor** do
resync — não participar de migração automática enquanto ele roda (regra 4), e o prazo da
`DEGRADADA` (regra 5) — não tem mecanismo nem dono: o executor é da `dr-003`, que não existe.
Deixa de ser aceito e vai para a candidata `C-006`.

**Decisão 2 — rebaixada.** "A interface precisa dizer" não tem mecanismo, e a interface não
tem momento marcado. Um item sem mecanismo e sem dono não é aceito, e o conserto honesto não
é achar dono: é parar de chamá-lo de aceito. A exigência foi escrita onde `degradada` é
definida — a seção "`degradada` é derivada, não marcada" da `dr-001` e o topo de `saude.py` —,
que é o que quem construir a tela vai ler; e a candidata `C-005` a guarda. O gatilho dela é
um evento, e não uma data.

**Decisão 3 — continua em análise, com dono honesto: as medições.** Mas a **`M4` mudou de
natureza**. Era descoberta — o bitmap sobrevive à migração automática? —, e o fornecedor
respondeu que sim, com storage compartilhado. Passa a ser **conferência de comportamento
documentado**: o fork da VHI marca `inconsistent` como o upstream diz? Mata o QEMU, reabre,
lê o campo. Binário, uma rodada, e muda a estimativa de quando a decisão 3 fecha: era a
medição que exigia dois nós e uma VM descartável, e agora é a mais barata das quatro. Se o
fork **não** marcar, é a coisa mais importante que podemos descobrir sobre esta plataforma.

E uma medição nova, que o ADR-0016 exige antes de o contrato do inventário ser desenhado:

| # | Medição | O que decide |
|---|---|---|
| M5 | **Por onde o estado do bitmap é legível na VHI.** `query-block` é QMP: pela API do libvirt, passthrough de monitor; ou pelo canal do agente no próprio nó. Ler os campos `recording`, `busy`, `inconsistent`, `granularity` e `count` de uma VM do laboratório pelos dois caminhos. | Se a leitura existe pelo caminho limpo. Se não existir por nenhum, o desenho do campo da `dr-001/T9` muda. |

Procedência: revisão do #38 e a pesquisa sobre o estado do bitmap; ver o ADR-0016.
