# ADR-0003: Plano de controle externo, plano de dados direto

**Data:** 2026-09-22
**Status:** aceito

## Contexto

A aplicação (interface, agendador, catálogo) precisa de um lugar para rodar. Uma opção
atraente é uma VM externa ligada remotamente aos dois clusters.

A pergunta é se os dados replicados também podem passar por ela.

## Decisão

O plano de controle roda fora dos dois clusters e conversa com eles só por HTTPS.
O plano de dados vai direto do hypervisor de origem para a receptora de destino, dentro de
um túnel privado (WireGuard) com TLS mútuo.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Blocos passando pela aplicação externa | Destrói o RTO e dobra o tráfego; a aplicação vira gargalo e ponto único de falha |
| Portas NBD expostas em IP público | Dispositivo de bloco gravável na internet; erro de configuração é catastrófico |
| APIs do OpenStack em IP público | Superfície de ataque muito maior que o NBD |
| Control plane dentro do DC-1 | Morre junto com o datacenter que ele deveria ajudar a recuperar |

## Consequências

Fica mais fácil: a aplicação sobrevive à perda de qualquer um dos dois lados; nada fica
exposto publicamente; o dado não faz escala.

Fica mais difícil: exige montar e manter o túnel. E impõe uma regra: durante um failover, o
control plane só pode depender de coisas do DC-2 — nem DNS, nem CA, nem banco no DC-1.
