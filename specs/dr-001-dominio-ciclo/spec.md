# dr-001 — Domínio e máquina de estados do ciclo

**Status:** rascunho
**Marco:** 1
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

O critério de saída do Marco 1 — *rodando sem hypervisor em menos de 2 segundos* — só é possível
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
| **Todo efeito que toca disco segura chaves de exclusão, uma por disco** | O id do ciclo não cobre isto: dois `blockdev-backup` concorrentes sobre o mesmo disco são **do mesmo ciclo**. Ver abaixo |

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

Por isso **todo efeito que toca disco segura chaves de exclusão, uma por disco que
toca** — `(vm, disco)`. Dois efeitos cujas chaves **se intersectam** nunca têm lease ao
mesmo tempo,
independentemente de ciclo.

#### Preempção: a única categoria que toma chave já tomada

A regra acima, sozinha, torna o cercamento impossível. `CercarDestino` toca disco, logo
carrega a chave `(vm, disco)` — e essa chave está presa pela cópia zumbi, que é a razão de
ele existir. O efeito que destrava não conseguiria lease, porque quem segura a chave é
exatamente quem ele destravaria. Disco bloqueado para sempre, e de volta o cenário que o
cercamento foi criado para eliminar.

Então existe uma **categoria** de efeito, e não uma exceção à regra: **efeito de preempção
toma chave já tomada, e é o único que pode.** Nomear a categoria é melhor que abrir buraco
na regra, porque a regra continua inteira para todo o resto e o buraco não cresce sozinho.

O que faz um efeito ser de preempção, e o que isso obriga:

| Propriedade | Por quê |
| --- | --- |
| Toma chave já tomada | É a definição. Nenhum outro efeito pode |
| **Nunca escreve dado de cliente** | Preempção *retira capacidade de escrever*; se escrevesse, seria mais um escritor concorrente — o problema, não a solução |
| É idempotente por construção | A segunda tentativa encontra o export já derrubado, e isso é sucesso, não erro |
| **O sucesso dele é evidência** | Derrubado o export, o escritor perdeu o alvo. É a terceira forma de evidência, e sem ela cercaríamos e continuaríamos esperando |
| **Coexiste com a chave; não despeja quem a tinha** | Ver abaixo — é a leitura que a implementação escolheria sem perceber que escolheu |

Hoje há um efeito de preempção: `CercarDestino`. A categoria existe para que o segundo,
quando aparecer, herde as obrigações em vez de recriá-las por analogia.

**"Toma chave já tomada" tem duas leituras, e só uma é segura.** Coexistir — agir apesar da
chave, e quem a tinha continua com ela — ou despejar, tirando a chave do detentor. A escrita
anterior não dizia qual, e quem implementasse escolheria uma sem perceber que estava
escolhendo.

É **coexistir**, e o motivo cabe numa frase: **preempção não precisa de exclusividade,
precisa de permissão para agir apesar da chave.** Exclusividade existe para impedir dois
escritores, e preempção não é escritor — a segunda obrigação já diz que ela nunca escreve
dado de cliente.

Despejar abriria um caminho ruim, e ele é alcançável com o que já está decidido: a fila
reentrega uma tentativa de `CercarDestino` do ciclo N por política de *retry*; a primeira já
tinha vencido, liberado a chave e fechado o N; o N+1 está com cópia viva. A tentativa
atrasada chega, é idempotente, encontra o export já derrubado e reporta sucesso — mas no
caminho **despejou o lease do N+1**, que estava copiando.

Com coexistir, nada disso acontece, por duas coisas já construídas: preempção não escreve, e
cercar identifica a **instância** — um cercamento atrasado do ciclo N só alcança o export do
ciclo N, que não existe mais.

Repare que a propriedade 3 não cobria isto: ela descarta **resultado** de ciclo que não é o
corrente, e efeito antigo ainda na fila é outra coisa. Para a preempção não é preciso regra
nova — coexistir mais nome por instância já a tornam inofensiva.

A chave nasce aqui, no tipo do efeito, e não na spec do protocolo: lá seria política de
fila sobre um tipo que não tem onde guardá-la. É o mesmo argumento que faz a serialização
nascer junto do tipo em vez de depois que a fila existir.

**E a chave sozinha não fecha o caso.** Ela torna a exclusão *dizível*; não diz quando
soltar. No cenário que a motivou o lease já **expirou** — a chave está livre justamente
enquanto o job continua escrevendo, e um segundo agente a toma sem violar regra nenhuma.
Então a chave vem com a condição de liberação: **chave de efeito que toca disco só é
liberada por evidência de que o job acabou, nunca pelo relógio do lease.**

#### Onde o efeito roda é parte do valor

Cercar roda **na receptora**, alcançada pelo túnel do relé. Copiar roda **no hypervisor de
origem**, alcançado pelo agente de lá. São dois alvos de execução diferentes, e a fila
precisa saber qual é o de cada efeito.

Se ela rotear todo efeito para "um agente com acesso àquele hypervisor", o `CercarDestino` é
inentregável exatamente no cenário em que existe — o erro do roteamento da evidência, um
nível acima. O `ConfirmarNoDestino` já tem essa natureza, então a distinção é real desde
antes; o que faltava era ela existir **no tipo**.

Mesmo argumento da chave: a fila só lê o que o valor carrega. O alvo de execução é campo do
efeito, não convenção de quem despacha.

**O critério de nomeação é modo de falha, não geografia.** Dois efeitos têm o mesmo alvo se,
quando um é inentregável, o outro também é. Por esse critério, "origem" e "destino" são
poucos: o Nova da nuvem de origem e o agente daquele mesmo hypervisor são **alvos
diferentes**, porque falham separado — e a segunda forma de evidência depende disso.

| Alvo | Caminho de alcance | Falha independente de |
| --- | --- | --- |
| `AGENTE_DE_ORIGEM` | agente no hypervisor da VM | todo o resto |
| `RECEPTORA` | túnel de saída da receptora até o relé | agente da origem |
| `API_DA_NUVEM_DE_ORIGEM` | control plane → Keystone/Nova, credencial do cofre | agente da origem |

Se `Alvo` tivesse só `ORIGEM` e `DESTINO`, a consulta ao Nova seria marcada `ORIGEM` e a
fila a entregaria a um agente daquele hypervisor — justamente quem não responde no cenário
em que a evidência do Nova existe para servir. Duas linhas da tabela acima estão do mesmo
"lado" e **não** podem compartilhar alvo.

#### A evidência é sobre o nó, e não sobre quem detém o lease

A consulta vai para o **nó declarado** — o nó onde o job foi iniciado, que o efeito carrega
no envelope — e é respondida por quem serve aquele nó agora, **não pela instância que detém
o lease**. `query-block-jobs` responde sobre o QEMU daquele nó, e o resultado diz qual nó
respondeu; resposta de outro nó não responde.

Está escrito aqui porque a implementação natural é a errada: buscar a evidência no detentor
do lease trava exatamente no cenário que a motivou — o agente está inalcançável, logo não
responde, logo não há evidência, logo a chave nunca libera, e a única saída vira mexer no
banco à mão.

Esta seção já disse "roteável por **qualquer** agente com acesso àquele hypervisor", e
estava errado: o QMP é um socket local do nó, e só quem serve o nó alcança o QEMU dele. Com
"qualquer agente", um agente de outro nó respondia com inventário vazio e a reconciliação
lia "não há órfão". Quando o agente do nó não responde, o caminho é o das duas seções
seguintes — o Nova, e o cercamento —, e não outro agente.

#### "A VM não está mais neste nó" também é evidência

Nó morto, ou VM migrada: não existe job para encontrar porque não existe quem responda. Com
uma forma só de evidência, um nó que morre bloqueia aquele disco para sempre.

A informação já está no desenho — é a detecção de troca de nó do
[ADR-0012](../../docs/adr/0012-resposta-a-perda-de-bitmap.md), que hoje leva a `degradada` e
resync controlado. Ela serve aqui porque **o escritor era o processo QEMU do nó antigo**: se
a VM não está mais lá, aquele escritor não existe mais. A evidência vem do Nova em vez do
libvirt, e continua sendo evidência.

#### Quando a evidência não chega, cerca-se

Evidência responde "o zumbi parou?". Existe mecanismo mais forte, e ele é nosso: **o destino
é nosso software**. O alcance até a receptora não passa pelo agente da origem — ela mantém
túnel de saída próprio para o relé, com a chave SSH restrita que o
[ADR-0011](../../docs/adr/0011-imagem-e-bootstrap-do-receptor.md) lhe entrega no bootstrap.
A receptora continua alcançável exatamente no cenário em que o agente da origem não está.

Então, em vez de esperar, **derruba-se o export NBD no destino**: `block-export-del` com
`mode: hard` desconecta cliente ativo. O `blockdev-backup` zumbi perde a conexão e morre sem
escrever mais nada — não porque provamos que parou, mas porque tiramos dele a possibilidade
de continuar. O `block-export-del` já é a mecânica de retirada de export do
[ADR-0010](../../docs/adr/0010-receptor-e-armazenamento-do-espelho.md); o que muda é o
`mode` e o motivo.

Três coisas que isso **não** muda:

- **A evidência continua sendo o caminho normal** — barata, sem efeito colateral. Cercar é o
  caminho de quando a evidência não chega.
- **Cercar não produz resync completo.** O custo é a janela pendente daquele ciclo, e a
  razão é `bitmap-mode: on-success`: o job abortado não limpou bitmap nenhum, então o ciclo
  seguinte recopia a janela inteira por cima das escritas parciais. A convergência não
  depende de o zumbi ter parado num ponto limpo.
- **P5 continua valendo.** Espelho meio escrito nunca é ponto de recuperação: o ponto é o
  snapshot Cinder, tirado entre ciclos. O último ponto bom fica intacto.

#### Publicar o export é passo do ciclo, e por isso é efeito

O export ser por ciclo tem consequência no vocabulário: **`PublicarExport` entra na
enumeração**, com alvo `RECEPTORA` e mecânica na `dr-006` — exatamente como o
`CercarDestino`.

Não é mudança de escopo entre specs; é a separação de duas coisas que estavam num passo só,
e que nunca tiveram o mesmo tempo de vida:

| Parte | Vida | Nome |
| --- | --- | --- |
| Volume espelho, anexação, `blockdev-add` | durável, atravessa ciclos | `(tenant_id, vm_id, disco)`, R3 da `dr-006` |
| `block-export-add` / `block-export-del` | por ciclo e por disco | derivado do ciclo e do disco |

O nó do `qemu-storage-daemon` é a anexação vista de dentro do daemon, e dura o que ela dura.
O export é o nome exposto na rede. `block-export-del`, inclusive com `mode: hard`, **remove
o export e deixa o nó**: o volume segue anexado, e o ciclo seguinte republica.

O que obriga a publicação a ser explícita é o que foi construído acima: se ela ficasse
escondida dentro do `IniciarCopia`, **a máquina não conheceria o nome do export que criou** —
e sem esse nome não há reconciliação de export órfão nem cercamento por instância.

Ganho de lado, que não foi o motivo mas vale registrar: export fechado entre ciclos deixa o
espelho gravável pela rede **só durante a janela de cópia**, em vez de sempre. Esta frase foi
falsa por um tempo: nenhum efeito retirava o export no fim do ciclo normal. Quem a torna
verdadeira é o `RetirarExport`, na fase de liberação. Menor
privilégio no tempo, sem custo.

#### O ponto cego do cercamento

O caminho de escrita do zumbi é origem → receptora, direto na 10809. O caminho do cercamento
é control plane → relé → receptora. **São caminhos diferentes**, e o túnel do relé pode cair
com a conexão de dados do zumbi intacta — aí não há evidência nem cercamento.

Existe nível acima, pela `API_DA_NUVEM_DE_DESTINO`: revogar a regra de security group que
libera a 10809 para o `/32` da origem mata o caminho de dados sem tocar no estado da
receptora, e não depende do relé.

**Fica para a v2**, e está registrado como candidata em
[`docs/pendencias.md`](../../docs/pendencias.md) para não morrer nesta conversa. A v1 assume
o ponto cego: os dois caminhos caírem juntos é mais raro que qualquer um deles cair, e a
consequência é a espera que o cercamento já reduziu, não corrupção nova.

**Compatibilidade.** `block-export-del` com `mode: hard` precisa ser conferido contra a
versão de `qemu-utils` do destino, que varia com o repositório do cliente — o
[ADR-0011](../../docs/adr/0011-imagem-e-bootstrap-do-receptor.md) já obriga o onboarding a
registrar a versão encontrada e rodar a suíte de compatibilidade contra ela. Se o `mode:
hard` não estiver lá, o cercamento vira reinício do `qemu-storage-daemon` daquela receptora:
mais grosseiro, mesmo efeito, e continua sem tocar em produção.

#### O custo, depois disso

Deixa de ser "agente inalcançável bloqueia aquele disco por tempo indeterminado" e passa a
ser **"agente inalcançável custa a derrubada de um export, e a janela pendente vai para o
próximo ciclo"**. Sem bloqueio indefinido e sem intervenção no banco.

#### De quem é cada parte

Pela tabela de [`specs/README.md`](../README.md):

| Parte | Onde |
| --- | --- |
| Os efeitos de publicar e cercar existirem na enumeração, e quando a máquina os pede | **`dr-001`** — é vocabulário de efeito e transição |
| A mecânica QMP no receptor (`block-export-del`, `mode`, fallback) | **`dr-006`**, que é dona do ciclo de vida do export |
| Rotear a consulta e a recusa de lease por chave | **Protocolo do agente** |

### Valor desconhecido de campo de segurança é recusa, não padrão

A evolução do contrato é aditiva: campo novo é opcional, e consumidor que não o conhece o
ignora. Isso resolve **campo** desconhecido e não resolve **valor** desconhecido de campo
que carrega regra — e o `Alvo` já prova que isso vai acontecer, porque a candidata da v2
acrescenta `API_DA_NUVEM_DE_DESTINO` à enumeração.

O cenário é concreto: v2 no ar, agente antigo num cliente, chega efeito com `alvo` que ele
não conhece. Se ele cair num padrão, roteia errado — que é exatamente o defeito consertado
nas últimas rodadas. Se ignorar o campo, pior.

**Valor desconhecido de campo que carrega regra de segurança é recusa.** O efeito volta para
a fila com "contrato mais novo que eu", e alguém vê. Vale para os três: `alvo`,
`chaves_de_exclusao` e a categoria de preempção — consumidor que não entende qualquer um
deles não pode executar assumindo o caso comum.

A distinção é entre **informação** e **regra**. Campo desconhecido continua ignorável, que é
o que "aditivo" significa; valor desconhecido de campo que decide para onde vai, com quem
conflita ou o que pode atropelar, não.

Sem esta regra, "versão do contrato não é campo" seria aposta de que todos os consumidores
estão sempre na mesma versão. Com ela, a decisão fica correta e a versão continua não sendo
campo.

### Tenant se diz uma vez

`tenant_id` está no envelope para a fila isolar sem abrir o efeito. Então que seja o
**único** lugar onde tenant aparece: nenhum corpo de efeito repete tenant, projeto ou
qualquer referência de onde ele possa ser derivado de novo. Duas expressões da mesma coisa
podem discordar — é o raciocínio que recusou a coluna `degradada` e a coluna `origem` na
auditoria.

Não é hipótese distante. Quando o `core-003` guardar efeitos em tabela com RLS, o
`tenant_id` do envelope é o discriminador, e integridade referencial no Postgres **ignora
RLS** — verificado na `core-001`. Id no corpo apontando para linha de outro tenant seria
oráculo de existência, que é o que o
[ADR-0006](../../docs/adr/0006-isolamento-por-rls.md) já tratou.

### Identidade é do domínio

Nome que precisa ser **reconhecido depois** não é infraestrutura, é identidade — e
identidade é do domínio. O formato da string é trivial; o que mora aqui é o mapeamento
**ciclo → nome**, que é conhecimento.

Vale para os três nomes que o ciclo cria:

- **bitmap temporário.** O laboratório usou `tmp1` cravado, e funcionou porque era um
  script, uma VM, uma execução por vez. Em produto colide: ciclo que morreu deixa `tmp1`
  órfão, e o seguinte tenta criar um bitmap que já existe;
- **checkpoint.** O laboratório usou `dr-<timestamp>`, que colide se dois ciclos começarem
  no mesmo segundo e não carrega identidade nenhuma. A reconciliação precisa mapear
  checkpoint para ciclo, e quem sabe esse mapeamento é a máquina.

- **export no destino.** Este entrou depois, pelo cercamento, e pelo mesmo motivo dos
  outros dois. `block-export-del` derruba *um* export, identificado por nome. Se o nome for
  fixo por disco e a tentativa seguinte recriar com o mesmo nome, um cercamento atrasado
  mata o job novo em vez do zumbi — o cercamento funciona e cerca a coisa errada, que é o
  pior defeito desta classe, porque parece ter dado certo.

  E ele é o único dos três que leva **também o disco** no nome. O export é um por disco, e
  o R5 da `dr-006` põe todos os discos de uma VM na **mesma** receptora — o mesmo servidor
  NBD, que escolhe export por nome. Com nome só por ciclo, o segundo `block-export-add` de
  uma VM com dois discos falharia. O checkpoint não leva disco porque é da VM, criado numa
  chamada só; o bitmap temporário não leva porque o QEMU separa nomes de bitmap por nó de
  bloco, e o mesmo nome em cada disco não colide.

Com o nome derivado do ciclo, **órfão tem definição**: nome de ciclo que não está ativo. A
limpeza deixa de ser heurística de prefixo, e **cercar identifica a instância** — o ciclo
e, no export, o disco.

Isto emenda a `dr-006`, e a emenda está lá: o **R3** manda derivar todo nome de
`(tenant_id, vm_id, disco)`, o que é certo para o volume espelho e a anexação, que
atravessam ciclos, e errado para o export, que é por ciclo. O ADR-0010 não fixa o nome do
export — ele descreve a mecânica e não a identidade —, então não precisa de emenda.

## Comportamento normal

Quando a VM entra e sai de proteção é ciclo de vida, e mora na
[`dr-006`](../dr-006-provisionamento/spec.md). Esta spec não nomeia esses estados. O que a
máquina do ciclo faz, com a VM em proteção:

1. Há uma janela aberta.
2. A cada intervalo do tier, um ciclo é elegível.
3. Ciclo fecha a janela corrente, abre a próxima, consolida as pendentes.
4. Cópia confirmada → ponto de recuperação registrado, janelas consolidadas liberadas.

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
| `migracao_detectada` | Job de resync criado, não iniciado ([ADR-0012](../../docs/adr/0012-resposta-a-perda-de-bitmap.md)). **Substituído** pelo [ADR-0016](../../docs/adr/0016-confianca-no-bitmap.md): o motivo passa a ser a condição do bitmap que falhou, e não o nó — na `dr-001/T6` |

**Esta é a única definição de `degradada`.** O ciclo de vida da VM é marcado e mora na
[`dr-006`](../dr-006-provisionamento/spec.md), que é quem nomeia os estados dele; a saúde é
derivada e mora aqui. A `dr-006`
já teve `degradada` como estado da máquina dela, com outro limiar, e a regra que resolveu a
contradição é essa: **ciclo de vida é marcado, saúde é derivada.**

E `degradada` **não é desprotegida**: os pontos de recuperação existentes continuam válidos.
O que para é a criação de pontos novos no ritmo prometido. A leitura natural de "degradada"
é "desprotegida", e a diferença é o produto inteiro.

**Quem exibir `degradada` exibe junto o ponto mais recente, e diz que ele continua
utilizável.** Está escrito aqui, e não só no ADR-0012, porque é aqui que quem constrói a tela
vai ler para saber o que `degradada` é — ninguém lê o ADR naquele dia. Ainda não há
mecanismo que o confira: a interface não existe, e a exigência é a candidata `C-005` de
[`docs/pendencias.md`](../../docs/pendencias.md).

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
- **P1/P2:** dois efeitos cujas chaves de exclusão se intersectam nunca têm lease ao mesmo
  tempo, e
  chave de efeito que toca disco só é liberada por evidência do hypervisor — nunca pelo
  relógio do lease.
- Nome de bitmap temporário e de checkpoint é derivado do ciclo, e o de export, do ciclo e
  do disco — nunca fixo.
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
- [ ] Todo efeito que toca disco segura chaves de exclusão, e elas sobrevivem à
      serialização — efeito sem chave não chega a existir
- [ ] Dois efeitos do **mesmo** ciclo sobre o mesmo disco produzem a mesma chave
- [ ] Efeito de VM e efeito de disco com **um** disco em comum se excluem — interseção, e
      não identidade de conjuntos
- [ ] Fechar a janela é **uma** unidade de execução, de VM, e não dois efeitos
- [ ] Chave de disco **não** é liberada por lease expirado, e **é** liberada por evidência
- [ ] VM que não está mais no nó gravado conta como evidência — nó morto não bloqueia disco
- [ ] Cercar o destino **não** dispara resync completo: o custo é a janela pendente
- [ ] Efeito que só a API da nuvem alcança **não** é roteado como efeito de agente
- [ ] Valor desconhecido de `alvo`, de chave ou de categoria é **recusado**, não assumido
- [ ] Preempção **coexiste**: o detentor da chave não perde o lease
- [ ] Nenhum efeito serializado contém segunda expressão de tenant
- [ ] `PublicarExport` produz um nome que a máquina reconhece depois — sem isso não há
      cercamento por instância nem reconciliação de órfão
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
