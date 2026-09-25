# dr-001 — Domínio e máquina de estados do ciclo

**Status:** rascunho
**Marco:** M1
**Depende de:** core-001

## Problema

A lógica difícil do DR — quando um ciclo pode avançar, quais janelas entram no delta,
quando disparar resync — precisa ser testável sem hypervisor. Se ela nascer dentro do
código que fala com libvirt, cada teste vai exigir um datacenter.

## Resultado esperado

`vzdr.core.domain` puro, sem IO, modelando VM protegida, ciclo, janela e ponto de
recuperação, e decidindo as transições. Testável em milissegundos num laptop.

## Conceitos

| Conceito | O que é |
| --- | --- |
| VM protegida | VM com tier, mapeamento de destino e flag de quiesce |
| Janela | Intervalo entre dois checkpoints; corresponde a um dirty bitmap |
| Ciclo | Uma execução: fecha janela, congela ponto-no-tempo, copia, confirma |
| Ponto de recuperação | Conjunto de snapshots de todos os volumes de uma VM, do mesmo ciclo |

## A máquina é pura; o agente são as mãos

O critério de saída do M1 — *rodando sem hypervisor em menos de 2 segundos* — só é possível
se a máquina **não executar nada**. Cada interação com QMP é um **efeito que ela pede**,
nunca algo que ela faz.

```
estado + resultado do efeito anterior  →  (novo estado, próximos efeitos)
```

Quem executa é o agente. Isso torna a máquina testável sem cluster e o agente substituível —
e é o que separa esta spec de uma que só roda em produção.

### Quatro exigências de forma

Entre a máquina pedir e o agente fazer existem **uma fila e uma rede**. O efeito não é uma
chamada de função adiada; é um registro que viaja.

| Exigência | Por quê |
| --- | --- |
| **Efeito é serializável** | O agente busca trabalho depois, de outro processo, talvez de outra máquina. Efeito que não cabe numa linha não sobrevive à fila |
| **Resultado é serializável e tolera repetição** | A rede cai entre concluir e reportar, e o agente repete. O protocolo do agente exige reporte idempotente, e é aqui que isso desce |
| **Todo efeito carrega o id do ciclo** | Senão um resultado atrasado do ciclo N chega quando a máquina já está no N+1, e ela o aceita como se fosse do atual |
| **Todo efeito que toca disco carrega chave de exclusão** | O id do ciclo não cobre isto: dois `blockdev-backup` concorrentes sobre o mesmo disco são **do mesmo ciclo**. Ver abaixo |

### Heartbeat que para não prova que o trabalho parou

O protocolo do agente concede trabalho por *lease* com heartbeat, e devolve o trabalho à
fila quando o heartbeat para. Mas heartbeat que para prova que **o reporte** parou, não que
o trabalho parou. Rede particionada, agente pausado, VM do agente suspensa: o job do QEMU
segue vivo do outro lado, escrevendo.

A terceira exigência não alcança este caso. Ela descarta resultado de **outro** ciclo, e
aqui os dois efeitos são do mesmo ciclo — o original, que ninguém cancelou, e o reemitido
depois que o lease caiu. A segunda também não: ela absorve reporte duplicado, que é
contabilidade, e o que está em jogo aqui são dois `blockdev-backup` escrevendo o mesmo
espelho. Resultado indefinido em cima do dado que o cliente vai usar no failover — é P1 e
P2, não desenho de protocolo.

Por isso **todo efeito que toca disco carrega uma chave de exclusão**, no mínimo
`(vm, disco)`. Dois efeitos com a mesma chave nunca têm lease ao mesmo tempo,
independentemente de ciclo.

A chave nasce aqui, no tipo do efeito, e não na spec do protocolo: lá seria política de
fila sobre um tipo que não tem onde guardá-la. É o mesmo argumento que faz a serialização
nascer junto do tipo em vez de depois que a fila existir.

**E a chave sozinha não fecha o caso.** Ela torna a exclusão *dizível*; não diz quando
soltar. No cenário que a motivou o lease já **expirou** — a chave está livre justamente
enquanto o job continua escrevendo, e um segundo agente a toma sem violar regra nenhuma.
Então a chave vem com a condição de liberação: **chave de efeito que toca disco só é
liberada por evidência do hypervisor de que o job acabou, nunca pelo relógio do lease.**
Que evidência é essa já está definida — é a reconciliação, e a regra de autoridade dela
vale inteira aqui: quem tem a palavra sobre o job é o hypervisor onde ele roda.

O custo é honesto e vale nomear: agente inalcançável **bloqueia aquele disco** até alguém
conseguir olhar o hypervisor. É lentidão, e a alternativa é corrupção silenciosa. Entre as
duas, a constituição já escolheu.

### Identidade é do domínio

Nome que precisa ser **reconhecido depois** não é infraestrutura, é identidade — e
identidade é do domínio. O formato da string é trivial; o que mora aqui é o mapeamento
**ciclo → nome**, que é conhecimento.

Vale para os dois nomes que o ciclo cria:

- **bitmap temporário.** O laboratório usou `tmp1` cravado, e funcionou porque era um
  script, uma VM, uma execução por vez. Em produto colide: ciclo que morreu deixa `tmp1`
  órfão, e o seguinte tenta criar um bitmap que já existe;
- **checkpoint.** O laboratório usou `dr-<timestamp>`, que colide se dois ciclos começarem
  no mesmo segundo e não carrega identidade nenhuma. A reconciliação precisa mapear
  checkpoint para ciclo, e quem sabe esse mapeamento é a máquina.

Com o nome derivado do ciclo, **órfão tem definição**: nome de ciclo que não está ativo. A
limpeza deixa de ser heurística de prefixo.

## Comportamento normal

1. VM protegida entra em `aguardando seed`.
2. Seed concluído → `protegida`, com uma janela aberta.
3. A cada intervalo do tier, um ciclo é elegível.
4. Ciclo fecha a janela corrente, abre a próxima, consolida as pendentes.
5. Cópia confirmada → ponto de recuperação registrado, janelas consolidadas liberadas.

## Reconciliação: o hypervisor tem a palavra sobre o hypervisor

O `dr-lab` morria e pronto. O produto não pode: **o agente cai no meio de um ciclo e o QEMU
continua copiando, ou não, independentemente do que o banco pensa.**

Então existe o estado `reconciliando`, e **entra-se nele em toda subida do agente**, não só
depois de queda. Caminho que só roda depois de queda é caminho que roda quando ninguém está
olhando.

### O que se compara

`query-block-jobs`, `checkpoint-list` e a lista de bitmaps, contra o que o banco pretendia.
O banco diz o que ela **pretendia**; o hypervisor diz o que **aconteceu**.

### De quem é a autoridade

| Sobre | Quem decide |
| --- | --- |
| Estado do hypervisor — job rodando, checkpoint existindo, bitmap presente | O hypervisor |
| Estado do destino — o dado chegou e foi gravado | O destino |

A distinção não é formalidade: **job concluído no hypervisor diz que a cópia saiu, não que
chegou**. P2 exige confirmação de gravação no destino, e nenhuma autoridade do hypervisor
passa por cima dela.

### As saídas

| O que a reconciliação encontrou | Para onde vai |
| --- | --- |
| Job ainda rodando | Volta a acompanhar, do ponto em que está |
| Job terminou e o banco não sabia | **Verificação no destino** — não "concluído" |
| Verificação no destino confirma | Ciclo conclui, ponto de recuperação registrado |
| Ciclo que o banco tinha e o hypervisor nunca viu | Encerrado com motivo `nunca_iniciou` |
| Divergência sem explicação | `precisa resync`, com o motivo |

Bitmap temporário de ciclo que não está ativo é órfão, e a reconciliação o remove — é o que
impede o ciclo seguinte de esbarrar num nome já existente.

## `degradada` é derivada, não marcada

`degradada` é **função de** `(idade do ponto de recuperação mais recente, RPO do tier)`.
Aritmética pura, calculada na hora de responder.

Não é marca que alguém liga e desliga: marca diverge do fato, e aí **a tela mente sobre
proteção** — que num produto de DR é a única coisa que ela não pode fazer.

**Padrão: degradada quando o ponto passa de 2× o RPO do tier.** Um ciclo perdido é ruído;
dois é padrão. E por tempo, não por tentativas: três falhas num tier de 1 hora e três num de
24 horas são situações diferentes, e contar tentativas trata as duas igual.

O **motivo** sim é registro, porque é o que a interface mostra e o que decide o que fazer:

| Motivo | O que acontece em seguida |
| --- | --- |
| `ciclo_falhou` | Segue tentando no ritmo do tier |
| `migracao_detectada` | Job de resync criado, não iniciado ([ADR-0012](../../docs/adr/0012-resposta-a-perda-de-bitmap.md)) |

E `degradada` **não é desprotegida**: os pontos de recuperação existentes continuam válidos.
O que para é a criação de pontos novos no ritmo prometido. A leitura natural de "degradada"
é "desprotegida", e a diferença é o produto inteiro.

## Janelas pendentes: alarme por volume, compactação por quantidade

Não existe limite de janelas pendentes que dispare resync. Um limite desses derrubaria a
invariante da falha por outro caminho — e a invariante vale mais que o limite.

Acumular custa duas coisas diferentes, e cada uma tem sua resposta:

**Volume do próximo ciclo.** Mais janelas, mais delta. É visível na telemetria e vira
**alarme**, não mudança de comportamento.

**Memória do QEMU, na VM do cliente.** Cada checkpoint retido segura um bitmap no processo.
Com a granularidade de 64 KiB medida no laboratório:

```
1 TiB / 64 KiB = 2^24 bits = 2 MiB de bitmap, por TiB
```

Na `instance-00000189`, de 2,5 TiB, são **5 MiB por bitmap**. Cem ciclos falhados são
**500 MiB** presos no processo que roda a VM do cliente — e isso machuca o cliente, não nós.

A resposta é **compactação**, não resync: apagar checkpoints intermediários faz o libvirt
mesclar o bitmap de cada um no pai. **A união se preserva, a informação não se perde**, e
sobra um bitmap em vez de cem. Nenhuma das duas respostas toca a invariante.

## Comportamento em falha

| Falha | O que acontece | Estado resultante |
| --- | --- | --- |
| Cópia falha no meio | Temporário descartado | Janela pendente acumula; próximo ciclo consolida duas |
| Ciclo falha N vezes seguidas | Alerta, VM marcada `degradada` | Segue tentando; RPO em risco visível |
| Divergência na reconciliação | Ciclo não executa | `precisa resync`, com o motivo |
| Um volume falha numa VM multi-disco | Ponto de recuperação inteiro descartado | Nenhum snapshot registrado |

## Telemetria do ciclo

Todo ciclo e todo resync **registra**, ao terminar — bem ou mal. É requisito, não
observabilidade opcional: sem estes campos as medições M1 e M3 do
[ADR-0012](../../docs/adr/0012-resposta-a-perda-de-bitmap.md) não existem, e a decisão do
resync diferencial fica sem os números que a fecham.

| Campo | Para quê |
| --- | --- |
| `bytes_transferidos` | Volume real por ciclo, que é a base de tudo |
| `duracao_por_fase` | Onde o tempo vai: checkpoint, cópia, commit |
| `vazao_media` e `vazao_pico` | Capacidade real do enlace, sem campanha de medição |
| `vazao_leitura_origem` | Dimensiona o resync diferencial (M1 do ADR-0012) |
| `throttle_vigente` | Separa "lento porque o link é ruim" de "lento porque foi limitado" |
| `motivo` | `ciclo`, `resync`, `seed`, `nunca_iniciou` — e, no resync, por quê |

`nunca_iniciou` é **achado de reconciliação, não falha de cópia**, e por isso tem motivo
próprio. Sem a distinção, ciclo que não aconteceu entra na taxa de falha junto com ciclo que
deu errado — e os números de confiabilidade passam a mentir justamente na métrica que vai
dimensionar o produto.

A diferença que isso faz: M1 e M3 deixam de ser campanha de laboratório e passam a ser
consulta ao banco depois de uma semana rodando, **com números do ambiente real do cliente
em vez de um teste sintético** ([ADR-0013](../../docs/adr/0013-orcamento-de-banda-e-janelas.md)).

Ciclo que falha registra igual, com o que conseguiu medir. Telemetria só do caminho feliz
descreveria um sistema que não existe.

## Invariantes

- **P2:** janela só é liberada após confirmação de gravação no destino.
- **P4:** falha nunca leva a resync silencioso nem a estado parcial aceito.
- **P5:** ponto de recuperação é atômico por VM, nunca por volume.
- **Falha de ciclo nunca causa resync completo.** O ciclo que falha descarta **apenas o
  bitmap temporário**; os checkpoints ficam intactos e o ciclo seguinte mescla uma janela a
  mais. Medido desde 2026-09-18, e é a propriedade que torna o mecanismo utilizável — se
  alguém a quebrar otimizando, o produto passa a copiar terabytes por causa de um timeout
  de rede.
- Todo efeito carrega o id do ciclo, e resultado de ciclo que não é o corrente é descartado.
- **P1/P2:** dois efeitos com a mesma chave de exclusão nunca têm lease ao mesmo tempo, e
  chave de efeito que toca disco só é liberada por evidência do hypervisor — nunca pelo
  relógio do lease.
- Nome de bitmap temporário e de checkpoint é derivado do ciclo, nunca fixo.
- Ciclo encerrado sem registro de telemetria é ciclo incompleto, inclusive quando falhou.
- `degradada` é calculada, nunca guardada.

## Critério de aceite

- [ ] Todas as transições têm teste, incluindo as inválidas
- [ ] Cada linha da tabela de falhas tem um teste
- [ ] Nenhum import de IO em `vzdr.core.domain` — verificado na CI
- [ ] Suíte roda em menos de 2 segundos
- [ ] Ciclo concluído e ciclo falho produzem telemetria, com teste para os dois
- [ ] **Falha de ciclo não dispara resync completo, em nenhum caminho** — o teste que
      protege a propriedade medida em 2026-09-18
- [ ] Resultado atrasado do ciclo N, chegando no N+1, é descartado
- [ ] Todo efeito que toca disco carrega chave de exclusão, e a chave sobrevive à
      serialização — efeito sem chave não chega a existir
- [ ] Dois efeitos do **mesmo** ciclo sobre o mesmo disco produzem a mesma chave
- [ ] Todo efeito e todo resultado sobrevivem a serialização e desserialização
- [ ] Resultado repetido não conta duas vezes nem vira erro
- [ ] `degradada` sai de conta sobre a idade do ponto, e não de campo guardado
- [ ] Reconciliação: job rodando, job terminado, ciclo que nunca existiu e divergência
      levam cada um à sua saída
- [ ] Job concluído no hypervisor sem confirmação no destino **não** conclui o ciclo
- [ ] Bitmap órfão de ciclo inativo é reconhecido como órfão

## Nada aqui dimensiona pelo laboratório

Dois números aparecem nesta spec, e só um é fato:

| Número | O que é |
| --- | --- |
| Granularidade de 64 KiB | **Fato medido** do QEMU deste parque. Entra na aritmética |
| VM de 2,5 TiB | **Ilustração** da conta, com uma VM real do laboratório. Não é premissa |

O laboratório da 4EDGE tem 11,83 TiB; o cliente-alvo tem 40 TB e **distribuição
desconhecida** — é a medição M2, ainda pendente
([P-002](../../docs/pendencias.md)). Nenhuma regra desta spec pode se apoiar na distribuição
do laboratório como se fosse a do cliente.

**Regra geral:** se algo aqui depender de perfil de parque, é **parâmetro com padrão**, não
constante. O limiar de `2× o RPO` para `degradada` e o limiar de compactação são os dois
casos — ambos parâmetros, ambos com padrão, nenhum derivado de um parque específico.

## Fora de escopo

Qualquer conversa com libvirt, QMP ou Cinder. Isso é `dr-002` e `dr-003`.

## Decisões que esta spec consome, e não redecide

- **A regra do nó** — nó diferente significa bitmap descartado, ciclo vira resync, evento
  próprio: [ADR-0012](../../docs/adr/0012-resposta-a-perda-de-bitmap.md), decisão 1, que é
  invariante de segurança e não escolha a testar.
- **A telemetria obrigatória por ciclo**:
  [ADR-0013](../../docs/adr/0013-orcamento-de-banda-e-janelas.md).
- **Os fatos do laboratório** — granularidade de 64 KiB, semântica de falha, `node-name`
  efêmero — estão em [`docs/01-arquitetura-dr.md`](../../docs/01-arquitetura-dr.md) e
  [`docs/validacao/`](../../docs/validacao/). O laboratório já pagou por eles.

## Perguntas em aberto

As duas originais estão respondidas acima, e uma delas foi **recusada como pergunta**:

- *Quantas falhas consecutivas marcam `degradada`?* — virou contagem por tempo, e
  `degradada` virou conta em vez de marca.
- *Janela pendente tem limite que dispara resync?* — **não**, porque derrubaria a
  invariante da falha por outro caminho. Virou alarme por volume e compactação por
  quantidade.

O que sobra:

- [ ] O limiar de compactação — a partir de quantos checkpoints retidos ela roda. Depende da
      curva de custo da mescla, registrada como medição na [fase 0 do
      roadmap](../../docs/03-roadmap.md), a rodar antes da `dr-003`. Não bloqueia o desenho:
      o limiar é parâmetro, e o desenho vale com qualquer valor.

`nunca_iniciou` **entra** na conta de `degradada` e **não** entra na taxa de falha. As duas
coisas são coerentes: `degradada` é aritmética sobre a idade do ponto de recuperação, e
ciclo que não aconteceu não produziu ponto — a idade não avançou, logo degrada. Já a taxa de
falha mede outra coisa, e "ciclo que não aconteceu" misturado com "ciclo que deu errado"
estragaria justamente a métrica que vai dimensionar o produto.

### Eventos

Esta spec ainda **não declara eventos**: a tabela `Eventos` entra na tarefa que os emite,
porque `check_eventos.py` exige emissor e teste. Os previstos ficam na `tasks.md`.
