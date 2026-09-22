# Visão

## O produto

O **vzdr** é uma plataforma de operação de infraestrutura: um app, várias features,
operado por interface gráfica, onde o operador nunca abre um terminal.

A primeira feature é DR. Monitoramento, backup, provisionamento self-service, capacidade
e chargeback entram depois como features, não como sistemas novos. Integrações com
sistemas externos entram como conectores.

## Zero-touch

Ninguém digita `virsh`, transação QMP ou chamada de API avulsa. Alocação de storage no
destino, criação de túnel, controle de checkpoints e medição de delta acontecem no
backend. A experiência se resume a: escolher a VM, definir três parâmetros, ativar.

## O que a interface nunca esconde

Automatizar não é trancar. Toda ferramenta de DR que escondeu tudo virou inútil no dia do
incidente. Três válvulas de escape são requisito:

- API e CLI equivalentes à interface
- Diagnóstico com o erro cru, sem tradução para mensagem genérica
- Preflight de failover visível antes do clique, nunca depois

## Regra de ouro

**O plano de controle roda fora dos dois clusters; o plano de dados viaja direto do
hypervisor de origem para a receptora de destino, dentro de um túnel privado.**

| Plano | O que trafega | Por onde |
| --- | --- | --- |
| Controle | Comandos, catálogo, estado, métricas | HTTPS para as APIs dos clusters |
| Dados | Blocos alterados | NBD sobre TLS, direto DC-1 → DC-2 |

Fazer os blocos passarem pela aplicação externa destruiria o RTO e dobraria a banda.

## Divisão núcleo / feature

Se duas features precisariam da mesma coisa, ela é do núcleo.

| Núcleo | Feature |
| --- | --- |
| Quem é o usuário e o que pode fazer | O que significa replicar uma VM |
| Quais sistemas externos existem e como falar com eles | Como funciona um ciclo incremental |
| Quais VMs, volumes e redes existem | Política de retenção |
| Executar trabalho agendado com estado | Ordem de boot no failover |
| Registrar e publicar o que aconteceu | Consistência multi-disco |

## O assistente de IA

Não é funcionalidade para o fim. É consumidor da API da plataforma, e será tão bom quanto
ela for. Por isso P7: toda funcionalidade existe em API antes de existir em interface.

O assistente age **como** um usuário, herdando o papel dele, nunca com privilégio próprio.
Ações destrutivas exigem confirmação humana mesmo quando o pedido veio dele.
