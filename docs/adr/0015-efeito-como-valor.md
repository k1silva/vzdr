# ADR-0015: A máquina de estados pede efeitos; não os executa

**Data:** 2026-09-25
**Status:** aceito

## Contexto

A `dr-001` modela o ciclo de replicação, e o critério de saída do M1 é que ela rode **sem
hypervisor, em menos de dois segundos**. Isso só é possível se ela não executar nada: cada
interação com QMP precisa ser algo que ela **pede**, não algo que ela **faz**.

Mas o ponto que força esta decisão agora não é testabilidade. É que o mesmo objeto atravessa
três coisas que ainda não existem juntas:

| Quem | Papel |
| --- | --- |
| `vzdr.core.domain` (dr-001) | Produz o efeito |
| A fila durável (`core-003`) | Guarda e entrega |
| O protocolo do agente | Transporta até o hypervisor e traz o resultado |

Quando as três existirem, a forma do efeito endurece. Decidi-la depois é renegociar um
contrato com três implementações no ar — a mesma razão que levou o ADR-0006 a ser escrito
antes da migração que o implementa.

## Decisão

A máquina é uma função:

```
estado + resultado do efeito anterior  →  (novo estado, próximos efeitos)
```

Ela devolve **efeitos como valores**. Quem executa é o agente, e o resultado volta pelo
mesmo caminho.

Quatro propriedades, e nenhuma é opcional:

### 1. O efeito é serializável

Não é *closure*, não é referência a objeto vivo, não é função. É um registro que cabe numa
linha de fila.

Entre a máquina pedir e o agente fazer existem uma fila durável e uma rede. O agente busca
trabalho **depois**, de outro processo, possivelmente de outra máquina e depois de um
reinício. Efeito que só existe na memória de quem o criou não sobrevive a nada disso.

### 2. O resultado é serializável e tolera repetição

Pelo mesmo motivo, e mais um: o agente pode entregar o **mesmo resultado duas vezes**. Rede
que cai entre concluir e reportar, *retry*, reinício no meio do reporte.

A máquina absorve a repetição sem duplicar estado. Isso é desenho de protocolo, não
tratamento de exceção — retrofitar depois é onde se ganha ciclo duplicado em produção.

### 3. Todo efeito carrega o id do ciclo

Resultado do ciclo N que chega quando a máquina já está em N+1 é **descartado**, não
aplicado.

Sem isso, um job lento vira corrupção de estado silenciosa: a máquina aceita como se fosse
do ciclo corrente, conclui uma janela que não foi copiada, e o dado do cliente fica com um
buraco que ninguém vê. É o tipo de defeito que só aparece em cliente com link ruim — e que
custa uma linha para fechar agora.

### 4. Todo efeito que toca disco carrega chave de exclusão

No mínimo `(vm, disco)`. Dois efeitos com a mesma chave nunca têm lease ao mesmo tempo,
independentemente de ciclo.

A propriedade 3 não cobre este caso, e é fácil achar que cobre: os dois efeitos em conflito
são **do mesmo ciclo** — o original, que ninguém cancelou, e o reemitido depois que o lease
caiu. A propriedade 2 também não: ela absorve reporte duplicado, que é contabilidade. Aqui
são dois `blockdev-backup` escrevendo o mesmo espelho, e o resultado é indefinido em cima do
dado que o cliente vai usar no failover. É P1 e P2 da constituição.

O que produz o conflito é que **heartbeat que para não prova que o trabalho parou** — prova
que o reporte parou. Rede particionada, agente pausado, VM do agente suspensa: o job do QEMU
segue vivo, escrevendo.

Daí a condição de liberação, que é metade da propriedade: **chave de efeito que toca disco
só é liberada por evidência do hypervisor de que o job acabou, nunca pelo relógio do
lease.** Sem ela a chave não resolve o cenário que a motivou, porque nele o lease já
expirou — a chave está livre justamente enquanto o job continua escrevendo.

O custo: agente inalcançável bloqueia aquele disco até alguém conseguir olhar o hypervisor.
Lentidão contra corrupção silenciosa, e a constituição já escolheu.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| A máquina chama o agente por uma interface (porta/adaptador) | Parece equivalente e não é: interface implica chamada síncrona no mesmo processo. A fila durável, o reinício do agente e o reporte idempotente deixam de caber. E a diferença não é de estilo: **valor se persiste, se inspeciona, se compara e se reexecuta; chamada de interface só se observa acontecendo** |
| A mesma, pela testabilidade | Recusada por colidir com regra escrita, o que é mais forte que recusa por desenho: "mockar libvirt ou QMP em teste de integração" está proibido no `AGENTS.md`. Interface empurra o teste para o mock; valor deixa o teste comparar registros |
| Efeito como *callable* ou *closure* | Não atravessa fila nem rede. Testável, mas só dentro do processo — e o agente roda noutra máquina |
| Resultado sem id de ciclo, confiando na ordem | A fila entrega fora de ordem depois de um retry, e um job lento chega atrasado por definição. Confiar na ordem é confiar em algo que o desenho não garante |
| Deixar a forma para quando a fila existir | É o que esta decisão evita. Três implementações no ar transformam mudança de forma em migração coordenada |
| Exclusão só no protocolo do agente, sem campo no efeito | Seria política de fila sobre um tipo que não tem onde guardá-la. Mesmo argumento da serialização: o que a fila precisa ler tem que existir no valor que ela guarda |
| Exclusão pelo `ciclo_id` que já existe | Não funciona no caso que importa. Os dois efeitos concorrentes são do mesmo ciclo |
| Reporte "exatamente uma vez" no protocolo | Não existe. O que existe é entrega pelo menos uma vez com absorção idempotente do outro lado, e é isso que a propriedade 2 assume |

## Consequências

Fica mais fácil: a máquina é testável sem cluster, em milissegundos; o agente é
substituível; um efeito perdido é reenviado sem cerimônia; e a fila do `core-003` guarda
valores, não promessas.

Fica mais difícil em três pontos concretos:

- **Toda mudança de efeito é mudança de contrato**, com fila e agente possivelmente numa
  versão anterior. Efeito ganha campo novo opcional; nunca muda significado de campo
  existente.
- **A máquina precisa ser explícita sobre o que espera**, porque não pode "chamar e ver".
  Estado que aguarda resultado é estado nomeado, não variável local.
- **Agente inalcançável bloqueia o disco dele** até haver evidência do hypervisor. É o
  preço da propriedade 4, e é deliberado.
- **Idempotência é obrigação de quem absorve**, e isso tem que ter teste. Resultado repetido
  não pode contar duas vezes — e é o tipo de coisa que passa despercebida porque o caminho
  feliz nunca a exercita.

Uma consequência que vale nomear porque parece detalhe: **o id do ciclo no efeito é o que
permite descartar sem ambiguidade**. Sem ele, "resultado atrasado" e "resultado do ciclo
atual" são indistinguíveis, e não há conserto posterior que recupere a informação perdida.
