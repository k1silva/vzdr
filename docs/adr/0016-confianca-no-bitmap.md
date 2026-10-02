# ADR-0016: A confiança no bitmap se lê do bitmap, e não do nó

**Data:** 2026-10-02
**Status:** aceito — substitui a decisão 1 do [ADR-0012](0012-resposta-a-perda-de-bitmap.md)
como teste de confiança do bitmap

> **Leia antes de implementar.** Este ADR decide **o que se lê e o que se responde**. Ele não
> decide **por onde se lê**: isso é a medição `M5`, e se a leitura não existir na VHI, o
> desenho do campo muda. E ele não constrói o resync: o gatilho é decisão, e cabe aqui;
> executar é da `dr-003`.

## Contexto

A decisão 1 do ADR-0012 usa a **comparação de nó** como teste de confiança do bitmap: nó
diferente do gravado, bitmap descartado e resync. Isso é procurador, e a evidência mostra
que ele erra **nos dois sentidos**. Não é desenho novo por gosto: é uma afirmação nossa
mostrada falsa, com a evidência nomeada.

**Nó igual não implica bitmap bom.** Um ciclo de energia do guest — RUNNING → POWEROFF →
RUNNING, sem crash, sem migração, mesmo nó — faz o libvirt converter os dirty-bitmaps em
bitmaps comuns; ao voltar, os checkpoints desapareceram e os bitmaps ficaram, e o backup
seguinte quebra com "Bitmap already exists". Registrado como falha real no OpenNebula
([one#6206](https://github.com/OpenNebula/one/issues/6206)). O mesmo erro aparece depois de
migração e de restauração, porque os metadados de checkpoint do libvirt não viajam com o
qcow2 ([virtnbdbackup#136](https://github.com/abbbi/virtnbdbackup/discussions/136)).

**Nó diferente não implica bitmap ruim.** Migração graciosa com storage compartilhado
preserva o bitmap: o fornecedor respondeu (P-001, fechada em 2026-09-29), e o upstream
documenta a migração de bitmaps persistentes.

**O bitmap diz de si mesmo se é confiável.** A documentação do QEMU
([interop/bitmaps](https://www.qemu.org/docs/master/interop/bitmaps.html)): o `query-block`
mostra, por bitmap, nome, granularidade e contagem de bytes sujos, e os indicadores
`recording`, `busy`, `persistent` e `inconsistent`. Bitmap `inconsistent` "was not saved to
disk correctly, and can no longer be used", e esse estado "prohibits almost all operations,
notably allowing only the `block-dirty-bitmap-remove` operation". `busy` "happens when the
bitmap is being used for a backup operation **or is in the process of being loaded from a
migration**". E o libvirt valida a cadeia antes de aceitar um incremental, em quatro
condições ([kbase: incremental backup](https://libvirt.org/kbase/internals/incremental-backup.html)):
a imagem do topo tem o bitmap; bitmaps de mesmo nome formam sub-cadeia contígua, sem
lacunas; todos estão `recording`; nenhum está `inconsistent`.

**Os dois limites desta evidência**, que não se herdam como certeza:

- é **upstream**, e a VHI roda um fork. Se o fork marca `inconsistent` como o upstream
  documenta é exatamente o que a `M4` passa a conferir (ver a emenda do ADR-0012);
- a página do libvirt descreve a validação e **não diz** que ele cai para cópia completa: ele
  recusa. O completo é decisão nossa — e é este ADR.

## Decisão

### 1. A confiança no bitmap é lida do próprio bitmap, em seis condições

Um incremental só começa se, para cada disco, a cadeia do nosso bitmap satisfaz as seis:

1. a imagem do topo tem o bitmap;
2. bitmaps de mesmo nome formam sub-cadeia contígua a partir do topo, sem lacunas;
3. todos estão `recording`;
4. nenhum está `inconsistent`;
5. o nome é o que o **nosso** ciclo criou: `ler_nome` devolve `NomeDeCiclo` da espécie certa.
   Nome nosso ilegível nunca é tocado; nome de outro ciclo não é nosso para confiar;
6. a granularidade é a que criamos. Granularidade diferente quer dizer que alguém recriou o
   bitmap — evidência de graça.

As quatro primeiras são as do libvirt; as duas últimas, nossas. O nó deixa de ser teste de
confiança: ele continua sendo onde a VM está, e é por isso que o inventário é pedido a ele.

**Mecanismo:** Mecanismo ainda não existe: `dr-001/T9` (o inventário traz, por disco e por
bitmap, o que as seis condições leem) e `dr-001/T6` (a máquina decide por elas).

### 2. Quatro respostas, e não duas

| Leitura | Resposta |
| --- | --- |
| cadeia válida pelas seis condições | incremental |
| `busy` | não começa; **repete**; reconciliação só depois de um prazo |
| ausente, com lacuna, não `recording`, ou `inconsistent` | resync completo |
| nome ou granularidade não são os nossos | órfão → reconciliação |

**`busy` tem duas causas, e uma passa sozinha.** Operação concorrente pede cercamento; carga
de migração chegando termina por si. Então `busy` é o único estado em que esperar e repetir
é a resposta certa antes de escalar — cercar um bitmap que só está terminando de carregar
derrubaria um export por causa de uma migração normal. O prazo é parâmetro, e não constante
tirada do laboratório.

**Mecanismo:** Mecanismo ainda não existe: `dr-001/T6` (as quatro respostas, e o prazo do
`busy`); o órfão, `dr-001/T7`.

### 3. O gatilho do resync é decisão; executá-lo é da `dr-003`

O ciclo que acha a cadeia inválida termina, sem copiar, e diz **qual condição falhou** — é
esse o motivo do resync, e substitui o `migracao_detectada` da decisão 1 do ADR-0012. Criar,
agendar e executar o job, bloquear migração enquanto ele roda e dar prazo à `DEGRADADA` são
do executor, que não existe; o que o ADR-0012 dizia sobre isso foi rebaixado e está na
candidata `C-006`.

Construir o executor aqui faria o ADR virar implementação, e o portão perderia o sentido.

**Mecanismo:** Mecanismo ainda não existe: `dr-001/T6` (o ciclo termina com o motivo).

### 4. O limiar vem do `count`, medido, e não de constante

O `count` diz quantos bytes estão sujos **antes** de copiar. "Incremental ou resync" passa a
ser comparação entre dois números medidos — `count` contra o tamanho total vezes um fator, e
o fator é parâmetro, como o de `degradada`. A regra de nunca derivar constante do
laboratório passa a ser cumprida por construção, e não por disciplina. Com o mesmo número: a
janela acumulada de um ciclo travado deixa de ser estimativa e vira leitura, cada ciclo
ganha ETA honesto, e a curva de custo da mescla ganha dado real.

**Mecanismo:** Mecanismo ainda não existe: `dr-001/T9` (o `count` no contrato) e `dr-001/T6`
(a comparação).

### 5. Por onde se lê é medido antes de o campo ser desenhado

`query-block` e `query-named-block-nodes` são QMP. Pela API do libvirt, isso tende a exigir
passthrough de monitor, e a regra de não brigar com o nova-compute vale aqui — leitura é
outra classe de risco que escrita, mas ainda é decisão. Se não houver caminho limpo pela API,
o agente lê pelo canal dele no próprio nó, que é onde ele já roda.

**Mecanismo:** Mecanismo ainda não existe: `M5`.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Manter a comparação de nó | É procurador, e erra nos dois sentidos: deixa passar o ciclo de energia do guest e manda para resync uma migração graciosa |
| Deixar o libvirt decidir e cair para completo quando recusar | Ele recusa e não decide; e a recusa não diz qual condição falhou, que é o motivo que o operador e o executor precisam |
| Resync completo depois de todo evento de host | Caro onde o bitmap sobreviveu, e cego onde não houve evento de host nenhum — o ciclo de energia |
| Duas respostas, com `busy` como resync | Uma migração chegando viraria resync, ou cercamento, por um estado que passa sozinho |

## Consequências

Fica mais fácil: o gatilho do resync deixa de depender da `M4` — ele é definível hoje. A `M4`
muda de natureza, de descoberta para conferência (ver a emenda do ADR-0012).

Fica mais difícil: o contrato do inventário cresce (`dr-001/T9`), e a leitura pode não existir
pelo caminho limpo (`M5`). O que a T5 entregou — `migracao_detectada`, a recusa de
`no_do_proximo_ciclo` — vale até a T9 e a T6 trocarem a comparação de nó pelas seis
condições.

O ciclo de energia do guest entra no desenho: ele deixa nome órfão, e a reconciliação o
recolhe (`dr-001/T7`).
