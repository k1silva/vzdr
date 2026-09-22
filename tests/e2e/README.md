# Testes ponta a ponta

Exigem dois clusters de laboratório e o túnel entre eles. Rodam antes de cada marco, não na
CI de cada commit.

## Cenários

- Ciclo completo DC-1 → DC-2, com ponto de recuperação verificado
- Queda de link no meio do job, retomada sem resync completo
- Test-failover em rede isolada, sem tocar na replicação corrente
- Failover e failback, com medição de RTO
