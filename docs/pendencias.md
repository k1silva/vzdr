# Pendências que atravessam documentos

Registro único de pendência que **não cabe** na seção "Em aberto" de uma spec nem no
roadmap.

## Por que existe um arquivo só para isto

A seção "Em aberto" de uma spec serve à spec: quem a implementa lê, decide, apaga a linha.
O roadmap serve aos marcos: o que entrega o quê, e quando.

Nenhum dos dois sustenta um item com estas três características ao mesmo tempo:

- **o dono está fora do repositório** — um fornecedor, um cliente, uma conta que ninguém
  aqui controla;
- **ele bloqueia uma decisão já registrada**, em geral num ADR;
- **ele aparece em mais de um documento**, e some justamente por isso: cada documento
  supõe que outro está cuidando.

Pendência que mora só na prosa de um documento some. Aconteceu perto de acontecer com o
limite de tentativa de senha por IP, que quase caiu entre a `core-001` e a `core-007`, e é
o que aconteceria com o chamado aberto do `dirty-bitmaps` se ele ficasse só no ADR-0012.

## A regra

Toda linha aqui tem **dono**, **data de revisão** e **o que ela destrava**.

Pendência sem data de revisão não é pendência, é esquecimento com boa intenção. Pendência
sem dono é pior: é a suposição de que alguém vai lembrar.

Chegada a data de revisão, o item muda de estado ou muda de data — com motivo. Não existe
"continua pendente" em silêncio.

**A data é de cada item, não do arquivo.** Duas pendências com a mesma data e dependências
diferentes viram uma data só que ninguém respeita. Por isso cada uma declara de que depende:
resposta de fornecedor e acordo comercial têm relógios próprios.

### Quem faz cumprir

`tests/invariants/check_pendencias.py`, na CI. Data de revisão vencida **falha o build**.

Isso é deliberado e tem um custo real: quebra a build de quem estava mexendo em outra
coisa. A alternativa — um aviso que não bloqueia — é o que este projeto já decidiu,
repetidas vezes, que ninguém lê. O conserto é legítimo e leva trinta segundos: ou o item
muda de estado, ou a data muda com motivo escrito na linha `Revisões`.

**E a renovação tem limite.** O modo de falha desta regra não é ela bloquear, é a renovação
virar carimbo: "+2 semanas, sem resposta ainda", indefinidamente, com a build verde e a
pendência morta. Ao chegar na terceira renovação o checador falha de novo e só sai com
mudança de estado — escalar, fechar, ou mover para "Candidatas". Renovar é barato uma vez;
na terceira, a pendência não está sendo tocada e isso precisa parar a linha.

## Abertas

### P-001 — a capability `dirty-bitmaps` está desligada no VHI

| | |
|---|---|
| **Pergunta** | Por que a capability `dirty-bitmaps` do QEMU está com `state: false` neste parque, e existe forma suportada de ligá-la? |
| **Dono** | Kawan |
| **Aberta em** | 2026-09-23 |
| **Revisar em** | 2026-10-08 |
| **Depende de** | resposta do fornecedor |
| **Estado** | aguardando o fornecedor |
| **Revisões** | nenhuma |

**O que ela bloqueia.** A medição **M4** do [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md):
se o bitmap sobrevive à migração automática do VHI. M4 exige cluster com mais de um nó e
VM descartável, e a resposta do fornecedor muda como o teste é feito — ou se ele é
necessário.

**O que ela destrava.** M4, junto com M1, M2 e M3, fecha a **decisão 3** do mesmo ADR: se
o resync diferencial é a próxima coisa depois da base ou se espera. Hoje essa decisão está
`em análise`, e o diferencial está desenhado mas não priorizado.

O sentido da resposta importa nos dois lados: se o bitmap **sobrevive**, a frequência de
resync despenca e o diferencial perde urgência; se **não sobrevive**, ganha.

**Onde mais aparece.** [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md) (contexto e M4),
[`docs/03-roadmap.md`](03-roadmap.md) (checklist de medições),
[`specs/dr-006-provisionamento/spec.md`](../specs/dr-006-provisionamento/spec.md) (em aberto).

### P-002 — distribuição do parque do cliente-alvo

| | |
|---|---|
| **Pergunta** | Qual a distribuição real dos 40 TB do cliente-alvo? |
| **Dono** | Kawan |
| **Aberta em** | 2026-09-23 |
| **Revisar em** | 2026-10-22 |
| **Depende de** | acordo de acesso ao ambiente do cliente — conversa comercial, não técnica |
| **Estado** | aguardando acesso |
| **Revisões** | nenhuma |

**O que ela bloqueia.** A medição **M2** do ADR-0012: rodar `scripts/censo-discos.sh` no
ambiente do cliente.

**O que ela destrava.** A mesma decisão 3. O censo do laboratório mediu 11,83 TiB com 76%
em três VMs, e essa distribuição **não serve de proxy**: quatro VMs de 10 TB no cliente
mudariam a conclusão inteira. É a medição que falta e que não está no laboratório.

**Onde mais aparece.** [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md),
[ADR-0008](adr/0008-modos-de-transporte.md) (tabela de tempo de seed),
[censo](validacao/2026-09-23-censo-do-parque.md).

## Candidatas

Itens que merecem virar trabalho, mas ainda não têm data.

- **Separar a decisão 3 do ADR-0012 num ADR próprio**, com status `proposto`. Aquele
  documento empacota três decisões de maturidade diferente, e foi por isso que ele não
  coube no vocabulário de status do `template.md`. A nota no topo é remendo, não conserto.
- **Uma *view* nomeando "ação veio por token"** na auditoria. Hoje o fato está lá e é
  inequívoco — `servico_id` é preenchido se, e somente se, a origem é serviço, garantido
  no `Principal` desde a T4 — mas a consulta exige que quem lê conheça o truque. Uma view
  chamada `auditoria_por_servico` (ou coluna derivada) paga-se quando existir tela de
  leitura de auditoria, em `core-007`. **Não** é coluna nova: `origem` seria segunda fonte
  de verdade para algo já inequívoco, e duas fontes podem discordar.
- **Restringir `ignore_missing_imports` do `mypy` a módulos de terceiros** — hoje é global,
  e foi o que tornou a ausência de `py.typed` invisível. Registrada como TI2 em
  `specs/core-001-tenancy/tasks.md`.

## Fechadas

Nenhuma ainda. Item fechado fica aqui com a data e a resposta — não some, senão perde-se
o motivo de a decisão ter sido tomada como foi.
