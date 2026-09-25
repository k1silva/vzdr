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
  - `nome_do_bitmap(ciclo_id)` e `nome_do_checkpoint(ciclo_id)`, puras e determinísticas.
  - Vem antes dos efeitos porque eles carregam esses nomes.
  - Testes: determinístico; ciclos diferentes nunca colidem; o nome permite reconhecer o
    ciclo de volta; nada de `tmp1` nem de `dr-<timestamp>`
  - Arquivos: `packages/core-domain/src/vzdr/core/domain/identidade.py`,
    `tests/unit/test_identidade.py`

- [ ] **T3** — Efeitos e resultados como valores
  - As três propriedades do ADR-0015, em código: serializável, resultado serializável e
    tolerante a repetição, `ciclo_id` em todo efeito.
  - **A serialização nasce junto do tipo**, com teste de ida e volta — não depois, quando
    a fila existir e a forma já estiver moldada pelo que foi escrito.
  - Testes: ida e volta de cada efeito e cada resultado; campo novo opcional não quebra
    quem lê a versão anterior; `Resultado` sem `ciclo_id` não existe
  - Arquivos: `.../domain/efeitos.py`, `tests/unit/test_efeitos.py`

- [ ] **T4** — `saude.py`: `degradada` é conta
  - `esta_degradada(idade_do_ponto, rpo, fator=2.0)`. Nenhuma transição a produz, nenhum
    campo a guarda.
  - O `fator` é parâmetro com padrão: depende de perfil de parque, e a spec proíbe
    constante derivada de parque.
  - Testes: 1× o RPO não degrada, 2× degrada; tier de 1h e de 24h tratados pela mesma
    conta; `nunca_iniciou` entra na idade do ponto e **não** na taxa de falha
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
  - Testes: a tabela inteira; o teste da invariante; resultado atrasado do ciclo N é
    descartado no N+1; resultado repetido não conta duas vezes
  - Arquivos: `tests/unit/test_ciclo_falha.py`

- [ ] **T7** — Reconciliação
  - `reconciliar(estado, inventario) -> Transicao`. Entrada separada porque é fotografia do
    hypervisor, não resultado de efeito pedido.
  - As cinco saídas da spec, e a regra de autoridade: hypervisor decide sobre o hypervisor,
    destino sobre o destino.
  - Testes: job rodando, job terminado, ciclo que nunca existiu, divergência; **job
    concluído no hypervisor sem confirmação no destino não conclui o ciclo** (P2); bitmap
    de ciclo inativo é reconhecido como órfão
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
