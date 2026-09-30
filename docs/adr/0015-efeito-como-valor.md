# ADR-0015: A máquina de estados pede efeitos; não os executa

**Data:** 2026-09-25
**Status:** aceito — propriedade 4 emendada em 2026-09-29; envelope emendado em 2026-09-30 (ver as emendas no fim)

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

**Mecanismo:** `tests/unit/test_efeitos.py::test_ida_e_volta`.

Não é *closure*, não é referência a objeto vivo, não é função. É um registro que cabe numa
linha de fila.

Entre a máquina pedir e o agente fazer existem uma fila durável e uma rede. O agente busca
trabalho **depois**, de outro processo, possivelmente de outra máquina e depois de um
reinício. Efeito que só existe na memória de quem o criou não sobrevive a nada disso.

### 2. O resultado é serializável e tolera repetição

**Mecanismo:** `tests/unit/test_efeitos.py::test_resultado_ida_e_volta`, `tests/unit/test_efeitos.py::test_resultado_repetido_e_o_mesmo_valor`; a absorção sem duplicar estado, `dr-001/T6`.

Pelo mesmo motivo, e mais um: o agente pode entregar o **mesmo resultado duas vezes**. Rede
que cai entre concluir e reportar, *retry*, reinício no meio do reporte.

A máquina absorve a repetição sem duplicar estado. Isso é desenho de protocolo, não
tratamento de exceção — retrofitar depois é onde se ganha ciclo duplicado em produção.

### 3. Todo efeito carrega o id do ciclo

**Mecanismo:** `tests/unit/test_efeitos.py::test_ciclo_id_viaja`, `tests/unit/test_efeitos.py::test_resultado_sem_ciclo_id_nao_existe`; o descarte do resultado atrasado, `dr-001/T6`.

Resultado do ciclo N que chega quando a máquina já está em N+1 é **descartado**, não
aplicado.

Sem isso, um job lento vira corrupção de estado silenciosa: a máquina aceita como se fosse
do ciclo corrente, conclui uma janela que não foi copiada, e o dado do cliente fica com um
buraco que ninguém vê. É o tipo de defeito que só aparece em cliente com link ruim — e que
custa uma linha para fechar agora.

### 4. Todo efeito que toca disco carrega chave de exclusão

**Mecanismo:** `tests/unit/test_efeitos.py::test_efeito_de_vm_e_efeito_de_disco_com_um_disco_em_comum_se_excluem`, `tests/unit/test_efeitos.py::test_so_preempcao_toma_chave_tomada`; a liberação só por evidência, `dr-001/T7`.

> **Emenda de 2026-09-29.** O texto abaixo é o original, mantido como registro do que se
> sabia. Duas correções, ambas por evidência:
>
> - **As chaves ficam no plural: uma por disco que o efeito toca.** Checkpoint e
>   congelamento são da VM — feitos disco a disco, cada disco teria um instante diferente,
>   e o ponto de recuperação pareceria válido sem ser. Esses efeitos seguram uma chave por
>   disco, e a fila concede todas de uma vez ou nenhuma, para não abrir impasse entre dois
>   efeitos segurando metades. A varredura do envelope perguntou o que a fila lê, e não de
>   quantos discos.
> - **"Mesma chave" passa a ser "chaves que se intersectam".** Lida sobre conjuntos, "mesma"
>   viraria "conjuntos idênticos", e um efeito de VM sobre três discos conviveria com um
>   efeito de disco sobre o segundo deles. Um disco em comum basta.
>
> O código está em `vzdr.core.domain.efeitos` (`EfeitoDeVm`, `se_excluem`), e o motivo de
> fechar a janela ser **um** efeito, e não dois, está no docstring de `FecharJanela`.

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
só é liberada por evidência de que o job acabou, nunca pelo relógio do lease.** Sem ela a
chave não resolve o cenário que a motivou, porque nele o lease já expirou — a chave está
livre justamente enquanto o job continua escrevendo.

Duas formas de evidência, e uma saída quando nenhuma chega:

- **`query-block-jobs`, roteável por qualquer agente com acesso àquele hypervisor.** Nunca
  perguntar ao detentor do lease: ele é justamente quem não responde no cenário que importa,
  e a regra travaria onde foi construída para proteger.
- **A VM não estar mais no nó gravado.** O escritor era o processo QEMU daquele nó; se a VM
  saiu, o escritor não existe. Vem do Nova em vez do libvirt, e continua sendo evidência.
  Sem esta segunda forma, um nó morto bloqueia aquele disco para sempre.
- **Cercar, quando nenhuma chega.** Derrubar o export NBD no destino (`block-export-del`,
  `mode: hard`) tira do zumbi a possibilidade de continuar, em vez de provar que ele parou.
  Funciona porque a receptora é nosso software e mantém túnel de saída próprio: ela está
  alcançável exatamente quando o agente da origem não está.

**E o cercamento é preempção, não trabalho concorrente.** A propriedade 4, sozinha, o
tornaria impossível: `CercarDestino` toca disco, logo carregaria a chave `(vm, disco)` — que
está presa pela cópia zumbi, que é a razão de ele existir. Por isso existe uma **categoria**
de efeito, e não uma exceção: efeito de preempção toma chave já tomada, é o único que pode,
nunca escreve dado de cliente, é idempotente por construção, **coexiste com a chave em vez
de despejar quem a tinha**, e **seu sucesso é evidência** — derrubado o export, o escritor
perdeu o alvo. Coexistir, porque preempção não precisa de exclusividade: precisa de
permissão para agir apesar da chave. Exclusividade existe para impedir dois escritores, e
preempção não é escritor. Categoria nomeada em vez de buraco na regra,
porque a regra continua inteira para todo o resto.

**Onde o efeito roda também é parte do valor.** Cercar roda na receptora, copiar roda no
hypervisor de origem. Fila que roteia tudo para "um agente com acesso àquele hypervisor"
torna o `CercarDestino` inentregável exatamente no cenário em que ele existe. O alvo de
execução é campo do efeito, pelo mesmo motivo que a chave é: a fila só lê o que o valor
carrega.

E o alvo se nomeia por **modo de falha, não por geografia**: dois efeitos têm o mesmo alvo
se, quando um é inentregável, o outro também é. Por esse critério o agente de um hypervisor
e o Nova da nuvem daquele hypervisor são alvos **diferentes** — e a segunda forma de
evidência depende disso, porque ela existe justamente para o caso em que o agente não
responde.

O custo, com as três: agente inalcançável custa a derrubada de um export e a janela pendente
daquele ciclo. Não é resync completo — `bitmap-mode: on-success` garante que o job abortado
não limpou bitmap, então o ciclo seguinte recopia a janela inteira por cima do que ficou
pela metade.

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
| Pedir a evidência ao agente detentor do lease | Trava no único cenário que a regra existe para cobrir: o detentor é quem não responde. A consulta é sobre o hypervisor, e qualquer agente com acesso a ele serve |
| Só evidência, sem cercamento | Nó morto não produz evidência nenhuma, e o disco ficaria bloqueado indefinidamente — trocando corrupção por indisponibilidade permanente |
| `CercarDestino` como exceção à propriedade 4 | Exceção abre buraco que cresce sozinho: o próximo efeito parecido vira segunda exceção por analogia. Categoria nomeada carrega obrigações — não escreve dado, é idempotente, seu sucesso é evidência |
| Alvo de execução deduzido do tipo do efeito pelo despachante | Conhecimento fora do valor, que some quando o efeito atravessa a fila. Mesmo erro da chave, e o `ConfirmarNoDestino` já provava que a distinção era real |
| Preempção despejando o detentor da chave | Abre caminho ruim alcançável com o que já está decidido: um `CercarDestino` reentregue por *retry* depois de o ciclo ter fechado despejaria o lease do ciclo seguinte, que está copiando |
| Valor desconhecido tratado com padrão seguro | Não existe padrão seguro para "para onde isto vai". Qualquer escolha é roteamento inferido, que é o defeito consertado três vezes |
| `Alvo` com dois valores, "origem" e "destino" | Geografia não é modo de falha. A consulta ao Nova cairia em "origem" e seria entregue ao agente do hypervisor — quem não responde no cenário em que essa evidência serve |
| Só cercamento, sem evidência | Derrubar export é barato mas não é grátis, e a maioria dos casos resolve com uma pergunta. Cercar é o caminho de exceção |
| Reporte "exatamente uma vez" no protocolo | Não existe. O que existe é entrega pelo menos uma vez com absorção idempotente do outro lado, e é isso que a propriedade 2 assume |

## Consequências

Fica mais fácil: a máquina é testável sem cluster, em milissegundos; o agente é
substituível; um efeito perdido é reenviado sem cerimônia; e a fila do `core-003` guarda
valores, não promessas.

Fica mais difícil em três pontos concretos:

- **Toda mudança de efeito é mudança de contrato**, com fila e agente possivelmente numa
  versão anterior. Efeito ganha campo novo opcional; nunca muda significado de campo
  existente.
- **Campo desconhecido se ignora; valor desconhecido de campo de segurança se recusa.** A
  regra aditiva resolve campo novo, não valor novo de enumeração que carrega regra. Um
  agente antigo que receba um `alvo` que não conhece e caia num padrão roteia errado — o
  defeito que a propriedade 4 e o `Alvo` existem para impedir. Ele devolve o efeito à fila
  com "contrato mais novo que eu". É o que permite a versão do contrato continuar não sendo
  campo sem virar aposta de que todos os consumidores estão na mesma versão.
- **A máquina precisa ser explícita sobre o que espera**, porque não pode "chamar e ver".
  Estado que aguarda resultado é estado nomeado, não variável local.
- **Agente inalcançável custa a derrubada de um export**, e a janela daquele ciclo vai para
  o próximo. É o preço da propriedade 4, e é deliberado.
- **O `mode: hard` depende da versão de `qemu-utils` do destino**, que varia com o
  repositório do cliente. O ADR-0011 já obriga o onboarding a registrar a versão e rodar a
  suíte de compatibilidade contra ela; sem o `mode: hard`, o cercamento vira reinício do
  `qemu-storage-daemon` daquela receptora.
- **Idempotência é obrigação de quem absorve**, e isso tem que ter teste. Resultado repetido
  não pode contar duas vezes — e é o tipo de coisa que passa despercebida porque o caminho
  feliz nunca a exercita.

Uma consequência que vale nomear porque parece detalhe: **o id do ciclo no efeito é o que
permite descartar sem ambiguidade**. Sem ele, "resultado atrasado" e "resultado do ciclo
atual" são indistinguíveis, e não há conserto posterior que recupere a informação perdida.

## Emenda de 2026-09-30: o efeito diz sobre o que ele é

O texto acima é o original. Esta emenda acrescenta, e não reescreve.

**Todo efeito tem sujeito** — o `vm_id` da VM do ciclo —, e **o efeito de agente diz em qual
nó roda**. A varredura do envelope perguntou o que o despachante lê e nunca perguntou se o
efeito tem sujeito, e dois efeitos de leitura nasceram sem: um inventário que não dizia de
onde, e uma consulta que não dizia de quem. Um inventário respondido pelo agente de outro
nó voltava vazio, e a reconciliação lia "não há órfão".

O critério do `Alvo` — mesmo alvo quando falham juntos — alcança o nó: agentes de nós
diferentes falham separado. O nó vem declarado, com a procedência da última consulta ao
Nova, e é conferido na resposta. "A VM não está neste nó" é desfecho próprio.

O `vm_id` dos efeitos de leitura **não** é chave de exclusão: com chave, a consulta de
evidência esperaria o lease preso pela cópia zumbi que ela existe para investigar.

Isto substitui um trecho da propriedade 4 acima: "`query-block-jobs`, roteável por
**qualquer** agente com acesso àquele hypervisor". O QMP é um socket local do nó, e com o nó
conferido na resposta, o agente de outro nó não responde por este. O que o trecho acertava
continua valendo — nunca perguntar à instância que detém o lease —; o "qualquer agente" era o
caminho do inventário vazio.

**Uma segunda receptora é valor novo de `Alvo`, e não `no` afrouxado.** O critério que pôs
o nó no efeito de agente — falham separado, logo são alvos diferentes — vale igual para
duas receptoras. Hoje há uma, e não morde. Mas o conserto óbvio de amanhã, permitir `no`
num efeito de receptora, mudaria o significado de um campo existente, de "proibido aqui"
para "permitido aqui" — o que este ADR proíbe: um efeito assim chegando numa versão antiga
cairia em `RegistroMalformadoError`, que descarta. Valor novo de `Alvo` é aditivo: a versão
antiga o recusa com `ValorDesconhecidoError` e devolve à fila, que é o caminho desenhado.

Procedência: revisão do #31, e o PR que implementa esta emenda.
