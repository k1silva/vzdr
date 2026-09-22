# Plataforma

## As capacidades do núcleo

| Capacidade | O que faz | Quem já precisa |
| --- | --- | --- |
| Identidade e tenancy | Usuários, organizações, papéis, permissões | Toda feature |
| Conexões e conectores | Registro tipado de sistemas externos | Toda feature |
| Cofre de segredos | Credenciais, certificados, chaves | Núcleo e features |
| Inventário | VMs, volumes, redes, hosts, sincronizados | DR, backup, monitoramento |
| Motor de trabalho | Fila durável com estado, retomada, agendamento | Ciclos, jobs, coletas |
| Frota de agentes | Registro, versão, saúde, comando | DR hoje, outras depois |
| Auditoria | Quem fez o quê, quando, em qual tenant | Toda feature |
| Eventos e webhooks | Barramento interno e assinatura externa | Alertas, integrações, assistente |
| Notificações | E-mail, webhook, chat | Toda feature |

## Conexões como conceito de primeira classe

Todo sistema externo entra como **conexão tipada** (P13). O conector declara schema de
configuração, credenciais, health check e capacidades. "Cluster VHI" é o primeiro tipo.

Isso é o que torna a plataforma integrável de verdade: adicionar Zabbix, NetBox, um
sistema de billing ou um bucket S3 é escrever um conector, não mexer no núcleo.

## Eventos nas duas direções

O barramento de eventos serve para dentro — uma feature reage ao que outra fez, sem se
conhecerem (P11) — e para fora, via webhooks, para que outros sistemas se inscrevam no que
acontece na plataforma.

É também o substrato que o assistente de IA vai consultar para responder "por que o RPO
da JAU-SERVER01 estourou ontem".

## Duas decisões que mudam o DR

**Inventário** não é do DR — é do núcleo. Um inventário de VMs, volumes, portas e redes
serve monitoramento, capacidade e billing igual. O DR vira consumidor e acrescenta só o
que é específico: qual VM está protegida, em que tier, com qual mapeamento.

**Frota de agentes**: o agente de replicação é uma *capacidade* do agente da plataforma,
que amanhã também coleta métrica e roda backup. Um agente por hypervisor.

## Monolito modular

Um deploy, fronteiras claras entre módulos no código. Microserviços nesse estágio é
armadilha: paga-se o custo de rede, observabilidade e deploy distribuído antes de ter
escala, e a fronteira que importa — a do domínio — se mantém com disciplina de código e
checadores na CI.

Extrair um módulo bem isolado depois é trabalho de dias. Reunir microserviços mal fatiados
é trabalho de meses. O agente nos hypervisors é a exceção óbvia.

## Banco

Um PostgreSQL, um schema por módulo, `tenant_id` em toda tabela. Feature não faz join na
tabela de outra: pede ao módulo dono.

## A armadilha

**A plataforma emerge da primeira feature; ela não é construída antes.**

O jeito clássico de matar um projeto assim é passar seis meses num framework elegante, sem
valor entregue e sem validação de que as abstrações estavam certas — porque nada real
passou por elas.

Construa cada capacidade do núcleo quando e porque o DR precisa dela, mas com a fronteira
no lugar certo. A segunda feature vai revelar onde ela ficou errada, e isso só é barato de
corrigir se os módulos estiverem separados desde o começo.
