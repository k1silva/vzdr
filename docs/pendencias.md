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

## Abertas

### P-001 — a capability `dirty-bitmaps` está desligada no VHI

| | |
|---|---|
| **Pergunta** | Por que a capability `dirty-bitmaps` do QEMU está com `state: false` neste parque, e existe forma suportada de ligá-la? |
| **Dono** | *a definir* — quem acompanha o chamado com a Virtuozzo |
| **Aberta em** | 2026-09-23 |
| **Revisar em** | 2026-10-08 |
| **Estado** | aguardando o fornecedor |

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
| **Dono** | *a definir* — depende de acesso ao ambiente do cliente |
| **Aberta em** | 2026-09-23 |
| **Revisar em** | 2026-10-08 |
| **Estado** | aguardando acesso |

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
- **Restringir `ignore_missing_imports` do `mypy` a módulos de terceiros** — hoje é global,
  e foi o que tornou a ausência de `py.typed` invisível. Registrada como TI2 em
  `specs/core-001-tenancy/tasks.md`.

## Fechadas

Nenhuma ainda. Item fechado fica aqui com a data e a resposta — não some, senão perde-se
o motivo de a decisão ter sido tomada como foi.
