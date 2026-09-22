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

## Invariantes

- **P2:** janela só é liberada após confirmação de gravação no destino.
- **P4:** falha nunca leva a resync silencioso nem a estado parcial aceito.
- **P5:** ponto de recuperação é atômico por VM, nunca por volume.

## Critério de aceite

- [ ] Todas as transições têm teste, incluindo as inválidas
- [ ] Cada linha da tabela de falhas tem um teste
- [ ] Nenhum import de IO em `vzdr.core.domain` — verificado na CI
- [ ] Suíte roda em menos de 2 segundos

## Fora de escopo

Qualquer conversa com libvirt, QMP ou Cinder. Isso é `dr-002` e `dr-003`.

## Perguntas em aberto

- [ ] Quantas falhas consecutivas marcam a VM como `degradada`?
- [ ] Janela pendente tem limite? A partir de quantas, resync completo compensa?
