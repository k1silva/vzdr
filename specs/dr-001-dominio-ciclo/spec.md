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

### Três exigências de forma

Entre a máquina pedir e o agente fazer existem **uma fila e uma rede**. O efeito não é uma
chamada de função adiada; é um registro que viaja.

| Exigência | Por quê |
| --- | --- |
| **Efeito é serializável** | O agente busca trabalho depois, de outro processo, talvez de outra máquina. Efeito que não cabe numa linha não sobrevive à fila |
| **Resultado é serializável e tolera repetição** | A rede cai entre concluir e reportar, e o agente repete. O protocolo do agente exige reporte idempotente, e é aqui que isso desce |
| **Todo efeito carrega o id do ciclo** | Senão um resultado atrasado do ciclo N chega quando a máquina já está no N+1, e ela o aceita como se fosse do atual |

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
- [ ] Todo efeito e todo resultado sobrevivem a serialização e desserialização
- [ ] Resultado repetido não conta duas vezes nem vira erro
- [ ] `degradada` sai de conta sobre a idade do ponto, e não de campo guardado
- [ ] Reconciliação: job rodando, job terminado, ciclo que nunca existiu e divergência
      levam cada um à sua saída
- [ ] Job concluído no hypervisor sem confirmação no destino **não** conclui o ciclo
- [ ] Bitmap órfão de ciclo inativo é reconhecido como órfão

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

- [ ] O limiar de compactação — a partir de quantos checkpoints retidos ela roda. Depende de
      medir o custo da mescla no laboratório, e não bloqueia o desenho.
- [ ] Se `nunca_iniciou` entra na contagem que alimenta `degradada`. A inclinação é sim, pela
      idade do ponto de recuperação, que é o que o cliente sente — mas confirmar com a tela
      na mão.

### Eventos

Esta spec ainda **não declara eventos**: a tabela `Eventos` entra na tarefa que os emite,
porque `check_eventos.py` exige emissor e teste. Os previstos ficam na `tasks.md`.
