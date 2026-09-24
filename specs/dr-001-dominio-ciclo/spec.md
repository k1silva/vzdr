# dr-001 — Domínio e máquina de estados do ciclo

**Status:** rascunho
**Marco:** M1
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

## Comportamento normal

1. VM protegida entra em `aguardando seed`.
2. Seed concluído → `protegida`, com uma janela aberta.
3. A cada intervalo do tier, um ciclo é elegível.
4. Ciclo fecha a janela corrente, abre a próxima, consolida as pendentes.
5. Cópia confirmada → ponto de recuperação registrado, janelas consolidadas liberadas.

## Comportamento em falha

| Falha | O que acontece | Estado resultante |
| --- | --- | --- |
| Cópia falha no meio | Temporário descartado | Janela pendente acumula; próximo ciclo consolida duas |
| Ciclo falha N vezes seguidas | Alerta, VM marcada `degradada` | Segue tentando; RPO em risco visível |
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
| `motivo` | `ciclo`, `resync`, `seed` — e, no resync, por quê |

A diferença que isso faz: M1 e M3 deixam de ser campanha de laboratório e passam a ser
consulta ao banco depois de uma semana rodando, **com números do ambiente real do cliente
em vez de um teste sintético** ([ADR-0013](../../docs/adr/0013-orcamento-de-banda-e-janelas.md)).

Ciclo que falha registra igual, com o que conseguiu medir. Telemetria só do caminho feliz
descreveria um sistema que não existe.

## Invariantes

- **P2:** janela só é liberada após confirmação de gravação no destino.
- **P4:** falha nunca leva a resync silencioso nem a estado parcial aceito.
- **P5:** ponto de recuperação é atômico por VM, nunca por volume.
- Ciclo encerrado sem registro de telemetria é ciclo incompleto, inclusive quando falhou.

## Critério de aceite

- [ ] Todas as transições têm teste, incluindo as inválidas
- [ ] Cada linha da tabela de falhas tem um teste
- [ ] Nenhum import de IO em `vzdr.core.domain` — verificado na CI
- [ ] Suíte roda em menos de 2 segundos
- [ ] Ciclo concluído e ciclo falho produzem telemetria, com teste para os dois

## Fora de escopo

Qualquer conversa com libvirt, QMP ou Cinder. Isso é `dr-002` e `dr-003`.

## Perguntas em aberto

- [ ] Quantas falhas consecutivas marcam a VM como `degradada`?
- [ ] Janela pendente tem limite? A partir de quantas, resync completo compensa?
