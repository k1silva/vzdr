# dr-001 — Tarefas

Cada tarefa cabe numa sessão de contexto e vira um commit.

Antes de cada uma: ler `spec.md`. Depois: `make check`. Nada aqui exige banco nem
hypervisor — se uma tarefa precisar, ela está no lugar errado.

- [x] **T1** — ADR-0015: a máquina pede efeitos, não os executa
  - Feito na fase de plano, e é por isso que está marcado antes de a primeira linha de
    código existir: o contrato entre a máquina, a fila do `core-003` e o protocolo do
    agente endurece quando as três existirem — mesma razão do ADR-0006 antes da migração
    da RLS. A T3 implementa o que ele decide.
  - Arquivos: `docs/adr/0015-efeito-como-valor.md`

- [ ] **T2** — Identidade do ciclo
  - `nome_do_bitmap(ciclo_id)`, `nome_do_checkpoint(ciclo_id)` e `nome_do_export(ciclo_id)`,
    puras e determinísticas. O export entrou pelo cercamento: nome fixo por disco faz um
    cercamento atrasado derrubar o export do ciclo seguinte.
  - Vem antes dos efeitos porque eles carregam esses nomes.
  - Testes: determinístico; ciclos diferentes nunca colidem; o nome permite reconhecer o
    ciclo de volta; nada de `tmp1` nem de `dr-<timestamp>`; os três nomes de um mesmo ciclo
    não colidem entre si
  - Arquivos: `packages/core-domain/src/vzdr/core/domain/identidade.py`,
    `tests/unit/test_identidade.py`

- [ ] **T3** — Efeitos e resultados como valores
  - As três propriedades do ADR-0015, em código: serializável, resultado serializável e
    tolerante a repetição, `ciclo_id` em todo efeito.
  - **A serialização nasce junto do tipo**, com teste de ida e volta — não depois, quando
    a fila existir e a forma já estiver moldada pelo que foi escrito.
  - **Chave de exclusão** (propriedade 4) em todo efeito que toca disco, no mínimo
    `(vm, disco)`. Nasce aqui e não na spec do protocolo: a fila só lê o que o valor
    carrega.
  - **`alvo` em todo efeito** (`ORIGEM` ou `DESTINO`). Cercar roda na receptora, copiar roda
    no hypervisor: fila que deduz o alvo do tipo torna `CercarDestino` inentregável no único
    cenário em que ele existe.
  - **`EfeitoDePreempcao`**, a categoria que toma chave já tomada — sem ela a propriedade 4
    torna o cercamento impossível, porque a chave está presa por quem ele vai derrubar.
    `CercarDestino` é o primeiro membro; a mecânica QMP é da `dr-006`.
  - Testes: ida e volta de cada efeito e cada resultado; campo novo opcional não quebra
    quem lê a versão anterior; `Resultado` sem `ciclo_id` não existe; efeito de disco sem
    chave não chega a existir; dois efeitos do **mesmo** ciclo sobre o mesmo disco produzem
    a mesma chave; a chave sobrevive à serialização; `alvo` sobrevive à serialização e
    `CercarDestino` é `DESTINO`; **só** efeito de preempção toma chave tomada; preempção
    repetida é sucesso, não erro
  - Arquivos: `.../domain/efeitos.py`, `tests/unit/test_efeitos.py`

- [ ] **T4** — `saude.py`: `degradada` é conta
  - `esta_degradada(idade_do_ponto, rpo, fator=2.0)`. Nenhuma transição a produz, nenhum
    campo a guarda.
  - O `fator` é parâmetro com padrão: depende de perfil de parque, e a spec proíbe
    constante derivada de parque.
  - **O relógio entra por parâmetro.** Nenhuma função do módulo chama `now()` — senão o
    teste não consegue fixar o instante, e a falha é silenciosa.
  - Testes: 1× o RPO não degrada, 2× degrada; tier de 1h e de 24h tratados pela mesma
    conta; `nunca_iniciou` entra na idade do ponto e **não** na taxa de falha; nenhuma
    função do módulo lê o relógio — verificado, não combinado
  - Arquivos: `.../domain/saude.py`, `tests/unit/test_saude.py`

- [ ] **T5** — A máquina: caminho normal
  - `avancar(estado, entrada) -> Transicao`. Função, não objeto: o estado entra e sai.
  - Testes: cada transição válida; transição inválida é recusada; a comparação do nó
    (ADR-0012) é a primeira coisa; toda saída pede efeito com `ciclo_id` correto
  - Arquivos: `.../domain/ciclo.py`, `tests/unit/test_ciclo.py`

- [ ] **T6** — A máquina: falha, e a invariante que mais importa
  - Cada linha da tabela de falhas da spec.
  - **O teste que protege a propriedade medida em 2026-09-18**: percorrer todos os caminhos
    de falha e afirmar que **nenhum** produz resync completo — só descarte do bitmap
    temporário, com os checkpoints intactos e uma janela a mais no próximo ciclo.
  - **Exigência de forma: parametrizado sobre a enumeração de falhas, não sobre lista
    escrita à mão.** Lista à mão não cobre o modo de falha que alguém acrescentar no ano que
    vem, e o teste segue verde depois de a propriedade já estar quebrada — cobertura
    aparente, de novo. Sobre o enum, falha nova é caso novo automaticamente.
  - É o teste mais importante do projeto, não só da spec: resync completo num cliente de
    40 TB é dias de janela, e a distância entre "degradou" e "inviabilizou o contrato" é
    exatamente esta propriedade.
  - Testes: a tabela inteira; o teste da invariante; resultado atrasado do ciclo N é
    descartado no N+1; resultado repetido não conta duas vezes; **cercar o destino não
    dispara resync completo** — o custo é a janela pendente, porque `bitmap-mode:
    on-success` garante que o job abortado não limpou bitmap e o ciclo seguinte recopia a
    janela inteira por cima do que ficou pela metade
  - Arquivos: `tests/unit/test_ciclo_falha.py`

- [ ] **T7** — Reconciliação
  - `reconciliar(estado, inventario) -> Transicao`. Entrada separada porque é fotografia do
    hypervisor, não resultado de efeito pedido.
  - As cinco saídas da spec, e a regra de autoridade: hypervisor decide sobre o hypervisor,
    destino sobre o destino.
  - **Liberação da chave de exclusão**: só por evidência de que o job acabou, nunca pelo
    relógio do lease. É aqui que a propriedade 4 do ADR-0015 fecha.
  - Duas formas de evidência: `query-block-jobs` **sobre o hypervisor** — roteável por
    qualquer agente com acesso a ele, nunca pedida ao detentor do lease — e a VM não estar
    mais no nó gravado, que é o Nova respondendo o que o libvirt não pode.
  - Quando nenhuma chega, a máquina pede `CercarDestino` — e **o sucesso dele é a terceira
    forma de evidência**: derrubado o export, o escritor perdeu o alvo. Sem isso cercaríamos
    e continuaríamos esperando.
  - Testes: job rodando, job terminado, ciclo que nunca existiu, divergência; **job
    concluído no hypervisor sem confirmação no destino não conclui o ciclo** (P2); bitmap
    de ciclo inativo é reconhecido como órfão; chave de disco **não** é liberada quando só o
    lease expirou, e **é** liberada quando o inventário mostra o job encerrado; VM fora do
    nó gravado libera a chave — nó morto não bloqueia disco; sem nenhuma das duas evidências,
    a saída é `CercarDestino` e não espera indefinida; **`CercarDestino` obtém lease mesmo
    com a chave presa pelo zumbi** — é o teste que a propriedade 4 sozinha reprovaria; o
    sucesso do cercamento libera a chave
  - Arquivos: `.../domain/ciclo.py`, `tests/unit/test_reconciliacao.py`

- [ ] **T8** — Telemetria
  - Os campos do ADR-0013, produzidos por ciclo concluído **e** por ciclo falho.
  - `nunca_iniciou` como motivo próprio, e teste de que ele não entra na taxa de falha.
  - É aqui que a tabela `Eventos` entra na spec, se algum evento for emitido por esta
    camada — ver "Eventos previstos".
  - Testes: ciclo concluído e ciclo falho produzem telemetria; ciclo encerrado sem
    telemetria é incompleto; `nunca_iniciou` separado da taxa de falha
  - Arquivos: `.../domain/ciclo.py`, `tests/unit/test_telemetria.py`

## Ordem

```
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8
```

- **T1 antes de tudo**: o ADR decide a forma que a T3 implementa.
- **T2 antes de T3**: os efeitos carregam os nomes.
- **T4 é independente** e pode sair de ordem — `saude.py` não depende da máquina.
- **T6 depois de T5**: não dá para testar falha de transição antes de haver transição.

## Eventos previstos

**Intenção, não contrato.** A tabela `Eventos` da spec é preenchida na tarefa que emite,
porque `check_eventos.py` exige emissor e teste.

| Evento previsto | Tarefa que o emite |
| --- | --- |
| `dr.ciclo_concluido` | T8 |
| `dr.ciclo_falhou` | T8 |
| `dr.migracao_detectada` | T5 — a comparação do nó (ADR-0012) |
| `dr.resync_necessario` | T7 |

Nomes conforme o [ADR-0005](../../docs/adr/0005-convencao-de-eventos.md): `dominio.acao`,
particípio, snake_case. **Quem emite** pode não ser esta camada — o domínio é puro e não
publica; quem publica é quem executa a transição. A tarefa decide, e a tabela da spec
registra.

## Fora desta lista

| O quê | Onde |
| --- | --- |
| Falar com libvirt, QMP ou Cinder | `dr-002` e `dr-003` |
| Persistir o estado do ciclo | `core-003` — fila durável |
| Entregar efeito ao agente e receber resultado | Protocolo do agente |
| Publicar os eventos no barramento | `core-006` |
| O limiar de compactação | Medição na fase 0 do roadmap, antes da `dr-003` |
| Executar a compactação | `dr-003` — é operação no hypervisor |
