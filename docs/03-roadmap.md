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

- [x] **Meta-checador bidirecional de coerência documento↔realidade** —
      `check_afirmacao_tem_mecanismo.py`, cobrindo por documento: hoje o plano da `dr-001`
      e o ADR-0015, com o resto impresso em toda execução. Nasceu vermelho nos três lugares
      previstos antes de rodar, e com um defeito próprio que a primeira execução mostrou.
      O texto original deste item segue: Afirmar que algo é
      verificado exige o mecanismo existir; afirmar que **não** é exige que ele não exista.
      Declaração estrutural, não textual — lista de exceção datada é o que se quer evitar.

      **Decisões esperando por ele.** Editam spec, e o gatilho do `specs/README.md` as
      segura. Moram aqui, e não em corpo de PR, porque decisão parada em PR some. Não são
      para responder agora — são para não serem respondidas por acidente, por quem estiver
      digitando na hora:

      1. **O terceiro estado numa função só, e os dois casos dentro dele.** `idade_do_ponto`
         devolve `None` sem ponto, mas `esta_degradada` não aceita `None`, e cada chamador
         reinventaria a decisão. Dentro de "sem ponto" há **dois casos opostos**: VM antes
         de `em_protecao`, que é esperado, e VM `em_protecao` sem nenhum ponto — o pior caso
         do produto, pior que `degradada`, porque não há o que restaurar. O dado que os
         distingue agora existe: o ciclo de vida da `dr-006`. Nenhum documento diz se o seed
         produz o primeiro ponto; se não produz, toda VM passa pelo pior caso entre o fim do
         seed e o primeiro ciclo, e alarmar ali seria ruído. A função de código,
         `classificar_protecao`, é aditiva em `saude.py`.
      2. **Quando uma VM multi-disco deixa `semeando`?** O R9 da `dr-006` só diz quando ela
         ganha ponto — todos os volumes no mesmo ciclo, que é P5. Não diz quando o seed
         termina: no último disco semeado, no primeiro, ou em outra condição. O item 1
         depende disto, porque distinguir "ainda no seed" de "em proteção sem ponto" exige
         saber onde fica a fronteira.
      3. **O que o teste da T5 protege.** `tasks.md` pede "a comparação do nó é a primeira
         coisa" — afirmação sobre a *implementação*, que o item 4 prevê trocar. Quando a M4
         fechar, esse teste fica vermelho com a propriedade intacta, e alguém mantém o
         mecanismo velho para mantê-lo verde. A propriedade que sobrevive à troca: **a
         validade do bitmap é decidida antes de qualquer trabalho caro**. O código da T5
         segue a propriedade; a redação de `tasks.md` muda quando o portão deixar, porque
         escolher o que um teste protege é decisão de desenho. A troca entra na
         `dr-001/T9` e na T6.

      4. **O disparo do resync deixa de ser a troca de nó**, se a M4 confirmar o sinal de
         consistência. Troca de nó era proxy, e a resposta da Virtuozzo o torna errado nos
         dois sentidos: migração graciosa troca de nó e não perde bitmap; queda pode perder
         bitmap sem trocar de nó. A troca de nó passa a ser motivo para **ir olhar**, não
         conclusão. A forma: **ADR novo**, e não reescrita do ADR-0012 — ADR registra por
         que se decidiu naquele momento, e reescrever apaga o que se sabia. O novo carrega
         a **procedência** (resposta da Virtuozzo mais medição da M4) e a **condição**
         (storage compartilhado). O 0012 ganha nota de status com **data e motivo**,
         apontando o trecho substituído — "substituído" responde o quê; quem lê depois
         precisa do porquê. O e-mail diz onde olhar, não o que se vai ver.
         **Feito em 2026-10-02, e sem esperar a M4:** o
         [ADR-0016](adr/0016-confianca-no-bitmap.md) decide o gatilho pelo comportamento
         documentado do upstream (QEMU e libvirt), e a M4 passa a **conferir** se o fork da
         VHI o segue. A candidata de separar a decisão 3 não foi resolvida de passagem: segue
         como `C-001` em `pendencias.md`.

      Os quatro são decisão de desenho, e o portão consolidado do `specs/README.md` os
      segura: ele cobre desenho, não conserto.

      **Resolvido no #31:** o nome do parâmetro de `esta_degradada` em `plan.md` e
      `tasks.md`. Era afirmação que o código demonstrava falsa — conserto, pela regra
      consolidada.

      **Resolvidas no #28:** a contradição entre `dr-001` e `dr-006` sobre `degradada`,
      arbitrada por regra — "ciclo de vida é marcado, saúde é derivada" —, e a linha de base
      falsa do `specs/README.md`.

      **E um limite deste checador como está desenhado**: ele confere afirmação de
      verificação contra mecanismo. Conceito **definido em dois lugares** é outra classe de
      defeito, e tem checador próprio: `check_definicao_unica.py`, no `make invariants`.
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
- [ ] **Profundidade de backing dos discos de dado, no parque.** A M5 leu
      `backing_file_depth: 0` numa VM, o que torna triviais as condições 1 e 2 do ADR-0016
      para ela. Não se generaliza: o censo confirma, VM a VM
      ([M5](validacao/2026-10-02-m5-leitura-do-bitmap.md)). É parte da **M2**: se o parque
      do cliente nunca tem profundidade > 0, o código de cadeia do inventário é peso morto;
      se tem, a forma é suposta e a `dr-001/T6` depende dela.
- [ ] **Taxa real de mudança** (M3 do ADR-0012) — `scripts/medir-taxa-mudanca.sh`, com
      bitmap, em amostra de **5 a 8 VMs cobrindo os perfis**, ao longo de 48 h. O método é
      o do [ADR-0012](adr/0012-resposta-a-perda-de-bitmap.md); esta linha dizia "20-30 VMs"
      e divergia dele
- [ ] **Sobrevivência do bitmap à migração e à queda** (M4 do ADR-0012) — **mudou de
      natureza em 2026-10-02**: de descoberta para conferência de comportamento documentado
      (ver a emenda do ADR-0012). A perna que decide é a da queda, e é binária. Desbloqueada: a
      Virtuozzo respondeu ([P-001](pendencias.md), fechada), e a resposta diz **onde olhar**,
      não o que se vai ver. Declaração não fecha medição. Em VM descartável, cluster com
      mais de um nó, duas pernas:
      - **saída pela porta** — criar bitmap persistente, migrar ao vivo, ler o bitmap no
        destino e conferir nome, granularidade e conteúdo;
      - **queda pela janela** — matar o processo QEMU da VM, reabrir, e ler o que o
        `query-block` reporta do bitmap persistido. A lembrança de duas pessoas é que o
        qcow2 marca como **inconsistente** o bitmap que não foi fechado limpo, e que o
        `query-block` expõe isso — ninguém verificou. Se existir, é o sinal que substitui a
        troca de nó: bitmap presente e consistente → confia; ausente ou marcado → resync.

        **Previsão, registrada antes de rodar** (2026-10-02, depois da M5 e da implicação
        do esquema QMP — inconsistente implica persistente, e nem `recording` nem `busy`):

        | Depois de matar o QEMU e religar | Leitura |
        | --- | --- |
        | `inconsistent: true`, `recording: false`, `busy: false`, `persistent: true` | o fork segue o upstream; o ADR-0016 fica de pé |
        | o bitmap ou o checkpoint desaparece | falha fechada por outro caminho, igualmente aceitável; muda o desenho, não a confiança |
        | `recording: true`, sem `inconsistent`, `count` preservado | alarme: o fork não marca, e a confiança no flag cai |

        Precisa de um nó que possa ser drenado.

        **E um passo a mais, de graça, se a leitura for `inconsistent: true`:** tentar
        `virsh checkpoint-delete <dom> <nome>` e registrar se funciona, se falha, e com qual
        erro. O QEMU só permite `block-dirty-bitmap-remove` num bitmap inconsistente, então
        é possível que o libvirt não consiga apagar o checkpoint cujo bitmap ficou assim — e
        a `dr-001/T7` precisa saber disso para ordenar o reparo. A M4 produz exatamente esse
        estado; repetir o laboratório só para isso seria outra sessão.

      E uma conferência que a resposta tornou necessária: o mecanismo só vale para bitmap
      **persistente**, e o repositório não registra como o bitmap temporário do laboratório
      foi criado. A regra não é "todo bitmap persistente". É **persistente onde a perda
      custa janela; não persistente onde a perda custa repetição**:
      - os bitmaps dos checkpoints carregam a janela, e perdê-los é resync — persistentes;
      - o temporário só congela a janela para uma cópia. Perdê-lo custa refazer a mescla, e
        é a linha "cópia falha no meio" da tabela de falhas da `dr-001` — coberta de
        verdade, não por acomodação. E ele **não deveria** ser persistente: persistente,
        sobreviveria à queda e viraria órfão para o ciclo seguinte limpar, trabalho criado
        sem benefício. Não persistente, evapora, que é o comportamento desejado.

      Confirmar os dois lados no laboratório. Se o bitmap voltar **limpo** depois de uma
      queda, o disparo por estado é pior que nenhum sinal — seria sinal errado.
- [ ] **Classificação das VMs por tier** — o critério escrito **antes** da lista, e a lista
      derivada dele. Na ordem inversa a classificação vira opinião por VM, e ninguém
      consegue dizer depois por que uma VM ficou no tier que ficou
- [ ] **Vazão real de seed entre os datacenters** (M1 do ADR-0012) — repetir o seed de
      2026-09-23 com `time`, medindo o mesmo volume, para converter tamanho em horas. Sem
      ela, toda estimativa de tempo de resync é chute, inclusive as dos próprios documentos
- [ ] **Custo da mescla de bitmap em função do número de checkpoints retidos** — cronometrar
      a mescla com 1, 2, 4, 8, 16 e 32 checkpoints retidos na mesma VM, e registrar a curva.
      Entra nela um caso que a `dr-001` cria: com um ciclo por vez por VM, um ciclo travado
      acumula a janela — cinco horas presas em `LOCALIZANDO` com RPO de uma hora fazem o
      ciclo seguinte copiar cinco horas de mudança. Os 2,8 MiB em 24 minutos do laboratório
      não dizem nada sobre essa janela nos 40 TB do cliente.
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
