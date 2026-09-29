# Roadmap

Seis marcos. Cada um termina com algo demonstrável e critério de saída objetivo.

## M0 — Fundação (2 semanas)

Repo, `AGENTS.md`, constitution, CI com lint, testes e invariantes, esqueleto do núcleo,
specs `core-001`, `core-002` e `dr-001` aprovadas.

**Sai quando:** `make check` verde na CI e uma spec passou pelo ciclo completo até `tasks`
sem você reescrever à mão.

### Estado em 2026-09-24

| Item | Estado |
| --- | --- |
| Repo, `AGENTS.md`, constitution | feito |
| CI com lint, tipos, testes e invariantes | feito — três jobs: `check`, `banco`, `alvo-py39` |
| Esqueleto do núcleo | feito |
| Spec `core-001` | **passou pelo ciclo completo**: spec, plano e tarefas; T1–T6b implementadas |
| Spec `dr-001` | aprovada, com a telemetria por ciclo do ADR-0013 |
| Spec `core-002` | **rascunho** — sem plano e sem tarefas |

**Falta para fechar:** levar a `core-002` até `tasks`.

O critério "VM de CI com libvirt 9.5 e QEMU 8.2" **saiu deste marco**. Ele nunca foi
cumprido e não podia ser: `tests/integration` nunca rodou, e um marco com critério que
ninguém consegue cumprir é um marco que ninguém usa. Virou item próprio em
"Pré-requisitos de infraestrutura".

O que isso **não** significa: a constituição proíbe mockar libvirt e QMP em teste de
integração, e continua valendo. O mecanismo foi validado contra libvirt e QEMU reais, no
cluster de laboratório, em 18 e 23 de setembro — à mão. Não é mock; é o mesmo teste sem
automação. Ver [validações](validacao/).

## M1 — Núcleo testável (2 semanas)

`core-001`, `core-003`, `dr-001`, `dr-002`. Máquina de estados, descoberta de discos,
estado durável. Nada ainda copia byte.

**Sai quando:** a máquina de estados cobre todos os cenários de falha, com teste para cada
um, rodando sem hypervisor em menos de 2 segundos.

### Fatia de manutenção, entre a `dr-001` e a `dr-002`

Cinco checadores, em commit próprio. Três vieram da varredura de fronteiras: são lugares
onde um documento afirma que algo é verificado e nada verifica.

**O gatilho não é data, é a próxima edição de spec** — e obrigatoriamente antes da `dr-002`.
O motivo está em [`specs/README.md`](../specs/README.md), onde quem vai editar uma spec o
lê.

- [ ] **Meta-checador bidirecional de coerência documento↔realidade.** Afirmar que algo é
      verificado exige o mecanismo existir; afirmar que **não** é exige que ele não exista.
      Declaração estrutural, não textual — lista de exceção datada é o que se quer evitar.

      **Decisões esperando por ele.** Todas editam spec, e o gatilho do `specs/README.md`
      as segura. Moram aqui, e não em corpo de PR, porque decisão parada em PR some:

      1. **A `dr-006` contradiz a `dr-001` sobre `degradada`**, em duas coisas. Natureza: a
         `dr-001` diz "derivada, não marcada", e a `dr-006` a tem como **estado** de uma
         máquina, com transições. Limiar: a `dr-001` diz "passou de 2× o RPO, por tempo e não
         por tentativas", e a `dr-006` diz "fora do RPO, **ou último ciclo falhou**". A
         proposta: **ciclo de vida é marcado, saúde é derivada**. A máquina da `dr-006` fica
         `pendente → provisionando → semeando → em_protecao`, e "em dia", "degradada" e "sem
         ponto" saem de `saude.py`.
      2. **O terceiro estado numa função só.** `idade_do_ponto` devolve `None` sem ponto, mas
         `esta_degradada` não aceita `None`, e cada chamador reinventaria a decisão. E dentro
         de "sem ponto" há **dois casos opostos**: VM ainda semeando, que é esperado, e VM em
         proteção sem nenhum ponto, que é o pior caso do produto — o operador acha que está
         protegido e não há o que restaurar. O dado que os distingue é o estado de ciclo de
         vida do item 1. Nenhum documento diz se o seed produz o primeiro ponto; se não
         produz, o pior caso acontece em toda VM entre o fim do seed e o primeiro ciclo.
      3. `esta_degradada(idade_do_ponto, ...)` virou `esta_degradada(idade, ...)` no código,
         por causa da sombra; `plan.md` e `tasks.md` da `dr-001` ainda mostram o nome velho.
      4. **A linha de base do `specs/README.md` é falsa.** Ela afirma que `dr-001` e `dr-006`
         conferem, "verificado à mão", e o item 1 mostra que não. O checador não pode nascer
         verde sobre ela.

      **E um limite deste checador como está desenhado**: ele confere afirmação de
      verificação contra mecanismo. O item 1 é outra classe de defeito — o mesmo conceito
      **definido em dois lugares**, que é "tenant se diz uma vez" aplicado a documento.
- [ ] **Todo arquivo de `tests/integration` referencia a fixture da conexão real.** Repare
      que a asserção é **positiva**. Procurar `unittest.mock` pega a forma óbvia e passa
      reto na que importa: uma classe `FakeQMP` escrita à mão, sem importar nada, satisfaz a
      mesma interface. Ausência de mock é impossível de provar; presença da conexão real é
      trivial de verificar, e um duplo escrito à mão não passa a satisfazê-la por acidente.
      Inofensivo hoje, porque a pasta está vazia; morde na `dr-002`
- [ ] **`gitleaks` na CI, mais checador próprio só para a regra do projeto** — DSN com senha
      fora de `scripts/ambiente_db.py`. Não reescrever scanner de segredo: a parte genérica
      é problema resolvido, e mal resolvido de novo é pior que ausente
- [ ] **`check_alvo_py39` varrendo também os blocos `python` de `specs/**/*.md` e
      `docs/**/*.md`.** Um `X | Y` passou pelo checador e pelo job `alvo-py39` porque estava
      num `.md`, não num `.py`. Isso é pior que um deslize de sintaxe: o plano é o que
      alguém copia, e a sintaxe errada não entra digitada no módulo — entra copiada de um
      documento que ninguém verifica
- [ ] **Texto do repositório e mensagem de commit só aceitam Latin mais pontuação.**
      Português precisa de acento, então a regra não é "só ASCII": é faixa Unicode
      permitida, e outro script é recusa. Nasceu de um `derivá-lo` com três caracteres
      cirílicos no meio, numa mensagem de commit — e a primeira tentativa de achá-lo falhou
      porque o padrão da busca tinha o mesmo defeito. **Varredura por faixa, não por texto**,
      que foi o que finalmente pegou

## M2 — Ciclo real (3 a 4 semanas)

`dr-003`, `dr-004`, `dr-005`, `core-004`. O agente replica de verdade, multi-disco, com
quiesce e reconciliação.

**Sai quando:** uma VM de vários discos replica por 72 h seguidas no laboratório,
sobrevivendo a uma queda de link provocada e a um reinício do agente, sem resync completo.

## M3 — Destino completo (3 semanas)

`dr-006`, `dr-007`, `dr-008`. Receptor provisionando, snapshots agrupados, TLS ponta a ponta.

**Sai quando:** cinco VMs replicam do DC-1 para o DC-2 pela WAN, com pontos de recuperação
visíveis no painel do VHI, e um deles é montado e verificado em máquina dedicada.

## M4 — Plataforma (4 semanas)

`core-005`, `core-006`, `core-007`, `dr-009`. Inventário, eventos, API, auditoria, plano de
failover em dry-run. A interface começa aqui.

**Sai quando:** o plano de failover sai sem pendências para o tier crítico, e tudo que a
interface faz também acontece pela CLI.

## M5 — Failover (4 semanas)

`dr-010`, `dr-011`. Execução, test-failover isolado, failback.

**Sai quando:** um test-failover completo sobe as VMs do tier crítico em rede isolada, com
aplicação respondendo, sem tocar em produção — e o failback devolve a operação ao DC-1
transferindo só o delta.

## Em paralelo — Fase 0 de medição

Roda junto com M0 e M1, precisa fechar antes do M3, porque dimensiona o storage do DC-2.

**Toda linha aqui carrega o método, não só o nome.** Medição registrada sem método é uma
medida diferente cada vez que roda, e a série não serve para comparar nada — que é o único
motivo de medir mais de uma vez. Quando o método mora num ADR, a linha aponta para lá em
vez de repetir, senão os dois divergem e nenhum dos dois é autoridade.

- [x] Censo de discos nos três nós (`scripts/censo-discos.sh`) — feito em 2026-09-23:
      11,83 TiB, 65 VMs, 115 discos.
      Ver [censo](validacao/2026-09-23-censo-do-parque.md)
- [ ] **Taxa real de mudança** (M3 do ADR-0012) — `scripts/medir-taxa-mudanca.sh`, com
      bitmap, em amostra de **5 a 8 VMs cobrindo os perfis**, ao longo de 48 h. O método é
      o do [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md); esta linha dizia "20-30 VMs"
      e divergia dele
- [ ] **Sobrevivência do bitmap à migração automática do VHI** (M4 do ADR-0012) — migrar
      uma VM descartável entre dois nós e conferir se o bitmap persiste. Exige cluster com
      mais de um nó. Bloqueado por [P-001](pendencias.md), chamado aberto com a Virtuozzo:
      a resposta muda como o teste é feito, ou se ele é necessário
- [ ] **Classificação das VMs por tier** — o critério escrito **antes** da lista, e a lista
      derivada dele. Na ordem inversa a classificação vira opinião por VM, e ninguém
      consegue dizer depois por que uma VM ficou no tier que ficou
- [ ] **Vazão real de seed entre os datacenters** (M1 do ADR-0012) — repetir o seed de
      2026-09-23 com `time`, medindo o mesmo volume, para converter tamanho em horas. Sem
      ela, toda estimativa de tempo de resync é chute, inclusive as dos próprios documentos
- [ ] **Custo da mescla de bitmap em função do número de checkpoints retidos** — cronometrar
      a mescla com 1, 2, 4, 8, 16 e 32 checkpoints retidos na mesma VM, e registrar a curva.
      É ela que define o limiar de compactação da
      [`dr-001`](../specs/dr-001-dominio-ciclo/spec.md), e precisa existir antes da `dr-003`.
      Sem a curva, qualquer limiar é chute com cara de número

## Pré-requisitos de infraestrutura

Bloqueiam o M3, não o início.

- [ ] **VM de CI com libvirt 9.5 e QEMU 8.2**, para automatizar `tests/integration`.
      Hoje esses testes rodam à mão contra o laboratório. Bloqueia o M2, cujo critério
      de saída é uma VM replicando 72 h seguidas — fazer isso à mão não escala.

      *Por que aqui e não em [`pendencias.md`](pendencias.md):* o critério de entrada de
      lá exige as três coisas ao mesmo tempo, e falta a decisiva — **dono fora do
      repositório**. Provisionar um runner é trabalho que controlamos. Ele atende as
      outras duas (bloqueia critério de marco, citado em mais de um documento), e é bom
      que o registro de pendências exclua alguma coisa: critério que aceita tudo vira
      depósito.

- [ ] Conta de serviço de API nos dois clusters
- [ ] Capacidade confirmada no DC-2
- [ ] Túnel WireGuard entre os datacenters
- [ ] VM de CI com libvirt 9.5 e QEMU 8.2
