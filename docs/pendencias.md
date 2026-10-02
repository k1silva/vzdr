# Pendências que atravessam documentos

Registro único de pendência que **não cabe** na seção "Em aberto" de uma spec nem no
roadmap.

## Por que existe um arquivo só para isto

A seção "Em aberto" de uma spec serve à spec: quem a implementa lê, decide, apaga a linha.
O roadmap serve aos marcos: o que entrega o quê, e quando.

Nenhum dos dois sustenta um item com estas três características ao mesmo tempo:

- **o desbloqueio depende de alguém fora do time** — um fornecedor, um cliente, uma conta
  que ninguém aqui controla. Repare que não é sobre quem está escrito na linha `Dono`: a
  P-002 tem dono interno e mora aqui mesmo assim, porque destravá-la exige um acordo de
  acesso que não se resolve daqui;
- **ele bloqueia uma decisão já registrada**, em geral num ADR;
- **ele aparece em mais de um documento**, e some justamente por isso: cada documento
  supõe que outro está cuidando.

**O que não entra em "Abertas", e o critério existe para isto.** Trabalho nosso, com
relógio nosso, não é pendência: medição de laboratório, dívida técnica, checador a escrever.
Isso mora na fase 0 do [roadmap](03-roadmap.md) ou nas tarefas de uma spec. A distinção não é burocracia — é o
que faz este arquivo responder a uma pergunta só, e ela é *o que precisamos cobrar de
fora*. Um item nosso misturado aqui não fica mais visível; ele apaga o sinal dos outros.

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

Itens que merecem virar trabalho, mas ainda não têm data — de qualquer origem, inclusive
nossa. O critério de "Abertas" **não** vale aqui: ele diz o que se cobra de fora, e isto é
estacionamento de ideia ainda sem forma. Item daqui que ganha data **sai** — para o roadmap
ou para as tarefas de uma spec — a menos que atenda ao critério de "Abertas", e aí sobe de
seção. Sem essa saída, a lista vira o depósito que o arquivo inteiro existe para evitar.

**O id (`C-NNN`) é para poder ser citado**, e não é prazo. Uma candidata pode sustentar uma
afirmação que uma emenda **rebaixou** — deixou de chamar de aceita porque não tem mecanismo
nem dono —, e o `check_afirmacao_tem_mecanismo.py` confere que ela existe. Só isso: candidata
nunca sustenta decisão viva, e o checador imprime em toda execução quantas afirmações estão
penduradas só nela. Se esse número sobe, aparece.

- **C-001 — Separar a decisão 3 do ADR-0012 num ADR próprio**, com status `proposto`. Aquele
  documento empacota três decisões de maturidade diferente, e foi por isso que ele não
  coube no vocabulário de status do `template.md`. A nota no topo é remendo, não conserto.
- **C-002 — Uma *view* nomeando "ação veio por token"** na auditoria. Hoje o fato está lá e é
  inequívoco — `servico_id` é preenchido se, e somente se, a origem é serviço, garantido
  no `Principal` desde a T4 — mas a consulta exige que quem lê conheça o truque. Uma view
  chamada `auditoria_por_servico` (ou coluna derivada) paga-se quando existir tela de
  leitura de auditoria, em `core-007`. **Não** é coluna nova: `origem` seria segunda fonte
  de verdade para algo já inequívoco, e duas fontes podem discordar.
- **C-003 — Cercamento por security group, na nuvem de destino** — a v2 do cercamento da
  [`dr-001`](../specs/dr-001-dominio-ciclo/spec.md). O cercamento da v1 tem ponto cego: o
  caminho de escrita do zumbi é origem → receptora, direto na 10809, e o caminho do
  cercamento é control plane → relé → receptora. O túnel do relé pode cair com a conexão de
  dados intacta, e aí não há evidência nem cercamento. Revogar a regra de security group que
  libera a 10809 para o `/32` da origem mata o caminho de dados sem tocar no estado da
  receptora e sem depender do relé. Usa o quarto alvo de execução,
  `API_DA_NUVEM_DE_DESTINO` — que já entrou na v1, pelo ponto de recuperação; o que esta
  candidata acrescenta é o efeito de revogar a regra, e não o alvo.
- **C-004 — Restringir `ignore_missing_imports` do `mypy` a módulos de terceiros** — hoje é global,
  e foi o que tornou a ausência de `py.typed` invisível. Registrada como TI2 em
  `specs/core-001-tenancy/tasks.md`.
- **C-005 — A interface diz que `degradada` não é desprotegida.** Decidido no ADR-0012
  (decisão 2) e rebaixado na emenda de 2026-10-02: não tem mecanismo, e a interface que o
  cumpriria não tem momento marcado. O gatilho é um **evento**, e não uma data — o dia em que
  alguém construir uma tela que mostre `degradada`. Por isso a exigência mora onde o conceito
  é definido, que é o que essa pessoa vai ler: a seção "`degradada` é derivada, não
  marcada" da [`dr-001`](../specs/dr-001-dominio-ciclo/spec.md), e o topo de `saude.py`.
- **C-006 — O que o executor do resync tem que garantir, herdado do ADR-0012.** A decisão 1
  daquele ADR dizia, sobre o executor: enquanto o resync roda, a VM não participa de migração
  automática (e, se a VHI não expuser como, o resync reinicia e o evento é registrado como
  `resync_interrompido_por_migracao`); e a `DEGRADADA` tem prazo — sem progresso por N horas,
  alarme e escalonamento. Rebaixado na emenda de 2026-10-02 porque o executor é da
  `dr-003`, que não existe. O gatilho é um evento: a spec da `dr-003` ser escrita.
- **C-007 — A identidade do agente no libvirtd do nó.** Ler o estado do bitmap exige
  `virDomainQemuMonitorCommand`, e o libvirt o recusa em conexão somente-leitura, mesmo para
  `query-*` (`virCheckReadOnlyGoto`, conferido no libvirt 9.5.0). A M5 foi feita como root.
  Então o agente precisa de identidade com acesso de leitura e escrita ao libvirtd, num nó
  que a Nova governa — peso de segurança, e decisão de implantação, não de domínio. O
  gatilho é um evento: o desenho de implantação do agente (`packages/agent`). Ver
  [a M5](validacao/2026-10-02-m5-leitura-do-bitmap.md).
- **C-008 — O backup nativo da VHI está habilitado nas VMs que o vzdr vai proteger?** Ele usa
  dirty bitmap nas mesmas imagens, com `compat: 1.1` como requisito. O desenho trata o
  `busy` que vier dele (repete, escala por prazo; nome que não é nosso é órfão), mas dois
  sistemas de backup nos mesmos bitmaps é o problema dos dois escritores um nível abaixo de
  onde se olhava. A resposta mora no ambiente do cliente, e chega com o mesmo acesso da
  [P-002](#p-002--distribuição-do-parque-do-cliente-alvo).

## Fechadas

Item fechado fica aqui com a data e a resposta — não some, senão perde-se o motivo de a
decisão ter sido tomada como foi.

### P-001 — a capability `dirty-bitmaps` está desligada no VHI

| | |
|---|---|
| **Pergunta** | Por que a capability `dirty-bitmaps` do QEMU está com `state: false` neste parque, e existe forma suportada de ligá-la? |
| **Dono** | Kawan |
| **Aberta em** | 2026-09-23 |
| **Revisar em** | 2026-10-08 |
| **Depende de** | resposta do fornecedor |
| **Estado** | **fechada em 2026-09-29** — o fornecedor respondeu |
| **Revisões** | nenhuma |

**O que ela bloqueia.** A medição **M4** do [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md):
se o bitmap sobrevive à migração automática do VHI. M4 exige cluster com mais de um nó e
VM descartável, e a resposta do fornecedor muda como o teste é feito — ou se ele é
necessário.

**O que ela destrava.** M4, junto com M1, M2 e M3, fecha a **decisão 3** do mesmo ADR: se
o resync diferencial é a próxima coisa depois da base ou se espera. **Desta pendência só é
dona a M4** — as outras três são trabalho nosso e moram na [fase 0 do roadmap](03-roadmap.md),
com exceção da M2, que tem pendência própria na P-002. Esta linha as cita para dizer de que
a decisão 3 depende, e não para guardá-las: medição rastreada dentro do texto de uma
pendência só é achada por quem lê a pendência inteira. Hoje essa decisão está
`em análise`, e o diferencial está desenhado mas não priorizado.

O sentido da resposta importa nos dois lados: se o bitmap **sobrevive**, a frequência de
resync despenca e o diferencial perde urgência; se **não sobrevive**, ganha.

**Onde mais aparece.** [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md) (contexto e M4),
[`docs/03-roadmap.md`](03-roadmap.md) (checklist de medições),
[`specs/dr-006-provisionamento/spec.md`](../specs/dr-006-provisionamento/spec.md) (em aberto).

**A resposta.** O bitmap sobrevive à migração ao vivo, sem mudança de configuração. O
`dirty-bitmaps` está desligado porque **não é usado**: ele governa transferir bitmap pelo
canal de migração, o que só é necessário quando os discos **não** estão em storage
compartilhado. No VHI estão, e o mecanismo é outro — a origem grava o bitmap dentro da
imagem antes de entregar a VM, e o destino o lê ao ativar. O bitmap viaja com o disco, não
com o fluxo de migração.

**O erro que a pergunta carregava.** `state: false` foi lido como "o mecanismo não
existe", e queria dizer "este mecanismo não é o usado". Fato lido como sinal de outra
coisa — a família de "ausência de check parece aprovação".

**O que a resposta fecha, e o que não fecha.** Fecha a pergunta desta pendência. Não fecha
a **M4**, que continua na [fase 0 do roadmap](03-roadmap.md): a resposta é declaração, não
medição, e agora a medição é barata e dirigida. E não fecha o caso que motivou o
ADR-0012: a resposta é sobre a saída pela porta — migração graciosa. Host que cai não
chega a gravar o bitmap na imagem; o resync controlado continua no desenho.

**A condição.** Vale **porque o storage é compartilhado**. Em VHI isso é propriedade do
produto, e vale para o cliente-alvo também — mas é condição, não lei universal.
