# Deploy

| Componente | Onde roda | Como |
| --- | --- | --- |
| API e agendador | Fora dos dois clusters | Container ou systemd |
| Agente | Cada hypervisor do DC-1 | systemd, veja `systemd/` |
| Receptor | VM no DC-2 | systemd, uma unidade `qemu-nbd` por volume espelho |
| PostgreSQL | Junto da API | Gerenciado ou container |

## Migrações

`migrations/` guarda o SQL versionado. A CI verifica que toda tabela tem `tenant_id` (P9).

Migração nunca roda automaticamente em produção, e nunca é executada por agente de IA.

## Túnel

WireGuard ponto a ponto entre os datacenters. O tráfego de replicação não divide interface
nem VLAN com o tráfego de serviço das VMs.
