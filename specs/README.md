# Specs

Uma pasta por feature, com `spec.md`, `plan.md` e `tasks.md`. Templates em `_template/`.

## Ordem de construção

Núcleo e feature intercalados: cada capacidade do núcleo nasce quando o DR precisa dela.

| # | Spec | Entrega | Depende de | Marco |
| --- | --- | --- | --- | --- |
| core-001 | Tenancy e identidade | Usuários, tenant, papéis, verificação de permissão | — | M0 |
| core-002 | Conexões e conectores | Registro de sistemas externos, conector tipado, cofre, health check | core-001 | M0 |
| dr-001 | Domínio e máquina de estados | VM protegida, ciclo, janela, ponto de recuperação | core-001 | M1 |
| dr-002 | Descoberta de discos e bitmaps | node-name, inventário de discos, leitura de bitmaps. **Cite [as pegadinhas do laboratório](../docs/01-arquitetura-dr.md#pegadinhas-descobertas-na-validação) antes da primeira linha:** `node-name` é efêmero, `qemu-img info` falha em volume de VM ligada | dr-001 | M1 |
| core-003 | Motor de trabalho | Fila durável, estado, retomada, agendamento | core-001 | M1 |
| dr-003 | Ciclo de replicação multi-disco | Checkpoint atômico, merge, backup job, commit. **Cite [as pegadinhas do laboratório](../docs/01-arquitetura-dr.md#pegadinhas-descobertas-na-validação) antes da primeira linha:** `bitmap-mode: on-success` com `sync: incremental`, `--quiesce` não existe neste fork, `raw` recusa checkpoint | dr-001, dr-002, core-003 | M2 |
| dr-004 | Quiesce com watchdog | freeze/thaw garantido, nível de consistência registrado | dr-003 | M2 |
| dr-005 | Reconciliação e resync | Detecção de divergência, decisão de resync | dr-003 | M2 |
| core-004 | Frota de agentes | Registro, versão, saúde, comando | core-002 | M2 |
| dr-006 | Provisionamento: proteger uma VM é um clique | Volume espelho, anexação, export, seed e entrada no ciclo — o fluxo inteiro, não só a mecânica do destino | dr-001, dr-002, core-002 | M3 |
| dr-007 | Pontos de recuperação e retenção | Snapshot Cinder por VM, política, expurgo | dr-006 | M3 |
| dr-008 | Transporte TLS | Credenciais, nó destino, throttle | dr-003, dr-006 | M3 |
| core-005 | Inventário | VMs, volumes, redes, hosts; sincronização e drift | core-002 | M4 |
| core-006 | Eventos e webhooks | Barramento de eventos, assinatura externa, entrega com retry | core-003 | M4 |
| core-007 | API e auditoria | FastAPI, OpenAPI, autenticação, RBAC, log imutável | core-001, core-003 | M4 |
| dr-009 | Plano de failover | Mapeamento DC1→DC2, preflight, dry-run | core-005 | M4 |
| dr-012 | Preparar ambiente de DR | Wizard de par de sites: projeto, rede, floating IP, receptora, bootstrap, orçamento de banda | core-002, core-003, core-007 | M4 |
| dr-010 | Failover e test-failover | Clone isolado, portas, VMs, ordem de boot | dr-007, dr-009 | M5 |
| dr-011 | Failback | Reversão do fluxo, só o delta do período de desastre | dr-010 | M5 |

A interface começa depois de `core-007`, consumindo a API. Pode correr em paralelo assim
que o contrato OpenAPI estabilizar.

## Antes de escrever uma spec de agente

As validações de 18 e 23 de setembro custaram dias e já estão escritas. A coluna "Entrega"
das specs que tocam libvirt ou QMP aponta para elas: leia antes, não depois.

O lugar dos fatos é [`docs/01-arquitetura-dr.md`](../docs/01-arquitetura-dr.md) e
[`docs/validacao/`](../docs/validacao/). O lembrete mora aqui, na tabela, porque este é o
primeiro arquivo que alguém abre ao começar uma spec — e pendência que mora só na prosa de
outro documento some.

## Antes de editar qualquer spec, a partir de agora

O **meta-checador bidirecional de coerência documento↔realidade** vem antes da próxima
edição de spec, e obrigatoriamente antes da `dr-002`. Ele está na fatia de manutenção do
[M1 do roadmap](../docs/03-roadmap.md).

O motivo de o gatilho ser este, e não uma data: cada spec editada antes de o checador
existir é uma edição cuja coerência ninguém conferiu. Passada a segunda ou a terceira, a
primeira execução dele deixa de distinguir "desviou" de "nunca foi conferido", e um
checador que não distingue as duas coisas nasce sem poder falhar.

**Uma correção, e ela vale mais que o texto que substitui.** Esta seção dizia que a
`dr-001` e a `dr-006` "conferem porque foram editadas juntas e lidas juntas", e chamava
isso de linha de base verificada à mão. Era falso: as duas definem `degradada` de modos
incompatíveis — derivada contra estado de máquina, 2× o RPO por tempo contra "último ciclo
falhou". Duas pessoas leram as duas specs, e nenhuma olhou a seção de estados da `dr-006`.

Verificação à mão que não verificou é o caso mais puro de afirmação com cara de conferência.
A consequência para os checadores é o inverso do que este texto prometia: eles **não podem
nascer verdes**, porque há contradição conhecida. Um checador que nasce vermelho sobre um
achado real prova, no primeiro segundo de vida, que consegue reprovar.

A `dr-001` T2–T8 não edita spec nenhuma, então a ordem combinada — código primeiro — não
esbarra nisto.

**O gatilho é sobre edição que cria ou altera afirmação**, não sobre marcar progresso:
marcar `[x]` num `tasks.md` não cria afirmação cruzada que possa divergir. Na dúvida,
**conta como afirmação** — e o PR que edita sob `specs/` diz qual leitura aplicou. Uma
linha, pela mesma razão da declaração de revisão: juízo declarado em vez de juízo
silencioso.

**Conserto de contradição registrada não é deriva.** Edição cujo único efeito é remover
uma contradição já registrada não cria afirmação — reconcilia duas que já existiam. Ela não
espera pelo checador, com duas condições:

- **o mecanismo que pega a contradição entra no mesmo commit**, de modo que edição e
  verificação chegam juntas ao `main`;
- **o registro prévio serve de evidência** — a contradição estava escrita antes, com as
  linhas, e não é descoberta feita durante a edição.

O motivo de estar escrito: o gatilho existe para que spec não derive antes de haver
mecanismo que pegue deriva. Travar o conserto atrás da ferramenta que detecta o defeito é
o gatilho trabalhando contra o próprio propósito — e esperar não melhora a linha de base,
que está sabidamente não conferida. Sem isto escrito, o próximo conserto bate na mesma
parede, e alguém resolve contornando em silêncio.

## O que toda spec responde

1. **Comportamento normal** — o caminho feliz, passo a passo.
2. **Comportamento em falha** — o que acontece em cada ponto de falha e o estado resultante.
3. **O que nunca pode acontecer** — as invariantes, ligadas aos princípios da constitution.
4. **Critério de aceite** — os testes que provam que está pronto.
5. **Fora de escopo** — explicitamente, para o agente não inventar.

O item 2 é o que mais rende num sistema de DR. O caminho feliz é a parte fácil.
