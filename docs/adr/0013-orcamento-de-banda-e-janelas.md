# ADR-0013: Orçamento de banda por par de sites, com janelas

**Data:** 2026-09-24
**Status:** aceito

## Contexto

A replicação lê do storage de produção do cliente e escreve na WAN dele. Ler na velocidade
máxima significa competir por I/O com as VMs que ele paga para rodar. Ninguém aceita isso
de dia; muita gente aceita de madrugada.

O laboratório de 2026-09-23 usou `speed: 52428800` fixo no `blockdev-backup`. Valor único,
cravado no script, igual às três da tarde e às três da manhã.

Duas observações mudam o desenho:

1. **O QEMU permite mudar a velocidade de um job em andamento** (`block-job-set-speed`). A
   transferência não precisa parar e recomeçar quando a janela vira — ela acelera.
2. **O throttle por job não controla nada.** Cinco jobs a 20% cada saturam o link enquanto
   cada um se comporta "educadamente".

## Decisão

### O orçamento é do par de sites, não do job

Cada par de sites declara uma **capacidade** no onboarding e um **orçamento** por janela. O
agente divide o orçamento vigente entre os jobs ativos daquele par e aplica a cada um com
`block-job-set-speed`.

Quando um job entra ou sai, o orçamento é redividido. Quando a janela vira, todos os jobs
ativos são reajustados — sem interromper nenhum.

```
par de sites:
  capacidade_declarada: 1 Gbps
  janelas:
    seg-sex 08:00-22:00  →  20%
    seg-sex 22:00-08:00  →  80%
    sáb-dom              →  80%
  override:
    "2026-10-03 22:00 → 2026-10-04 06:00 : 100%"
```

### Capacidade é declarada, não medida

Na v1 a capacidade do enlace é informada no onboarding e o percentual incide sobre ela.
Medição adaptativa da banda disponível é refinamento posterior: exige sondagem própria,
que é mais uma coisa competindo pelo link que se quer poupar.

Consequência honesta: capacidade declarada errada produz throttle errado. O onboarding
registra quem informou e quando, e a telemetria de vazão real (ver abaixo) permite
confrontar o declarado com o observado.

### Override manual é operação de primeira classe

"O cliente liberou hoje à noite" é o caso comum, não a exceção. O override tem início, fim,
percentual, autor e motivo, e **expira sozinho**. Override sem prazo não existe — é assim
que um throttle temporário vira permanente e ninguém lembra por quê.

### Prioridade entre jobs

Dentro do orçamento, a divisão não é igualitária: um resync de VM em `DEGRADADA` tem
prioridade sobre um ciclo de rotina, porque o primeiro está com o ponto de recuperação
congelado e o segundo não. A política é configurável; o padrão é resync antes de ciclo.

### Telemetria: o produto mede a si mesmo

Todo ciclo e todo resync registra, no mínimo:

| Campo | Para quê |
|---|---|
| bytes transferidos | volume real por ciclo |
| duração por fase | onde o tempo vai |
| vazão média e de pico | **capacidade real do enlace**, sem campanha de medição |
| vazão de leitura na origem | dimensiona o resync diferencial (M1 do ADR-0012) |
| throttle vigente | separa "lento porque o link é ruim" de "lento porque foi limitado" |
| motivo do job | ciclo, resync, seed, e por quê |

Isso não é observabilidade opcional. As medições M1 e M3 do
[ADR-0012](0012-resposta-a-perda-de-bitmap.md) deixam de ser campanha de laboratório e
passam a ser consulta ao banco depois de uma semana rodando — **e vêm do ambiente real do
cliente, não de um teste sintético**.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Throttle fixo por job, como no laboratório | Não controla o agregado. N jobs concorrentes saturam o link com cada um "comportado". |
| Parar e recomeçar o job na virada de janela | `block-job-set-speed` existe. Recomeçar descartaria progresso e criaria um ponto de falha a cada virada. |
| Medir a banda disponível e adaptar sozinho | Exige sondagem, que compete pelo link que se quer poupar. Fica para quando houver telemetria suficiente para inferir sem sondar. |
| Percentual sobre banda medida em vez de declarada | Mesma objeção. E capacidade declarada, mesmo imperfeita, é auditável: alguém assinou embaixo. |
| Override sem prazo | Vira permanente e ninguém lembra por quê. Todo override expira. |

## Consequências

- O agente precisa de um coordenador por par de sites que conheça todos os jobs ativos. Um
  agente por hypervisor decidindo sozinho não consegue dividir orçamento.
- Virada de janela é evento agendado que toca todos os jobs ativos. Precisa ser idempotente:
  reajustar duas vezes para o mesmo valor não pode quebrar nada.
- Fuso horário é do **cliente**, não do servidor. "22:00" tem que significar 22:00 onde o
  cliente está. Erro clássico e caro.
- Um job iniciado às 21:50 continua e acelera às 22:00. Não há recomeço, o que também
  significa que não há ponto natural de reavaliação — a virada precisa ser disparada.
- A telemetria vira dado de negócio: "quantos resyncs foram causados por migração" e "qual a
  vazão real do enlace deste cliente" saem da mesma tabela.
