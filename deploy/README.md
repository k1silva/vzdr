# Deploy

| Componente | Onde roda | Como |
| --- | --- | --- |
| API e agendador | Fora dos dois clusters | Container ou systemd |
| Agente | Cada hypervisor do DC-1 | systemd, veja `systemd/` |
| Receptor | VM no DC-2 | systemd, uma unidade `qemu-nbd` por volume espelho |
| PostgreSQL | Junto da API | Gerenciado ou container |

## Migrações

`migrations/` guarda o SQL versionado. A CI verifica que toda tabela que guarda dado de
tenant tem `tenant_id` (P9), com a lista de exceções fechada em
`specs/core-001-tenancy/spec.md`.

Aplicar, a partir da raiz do repositório:

```bash
make db-up
python -m scripts.migrar
```

Não há Alembic: sem ORM, ele não entregaria o que justifica seu uso. O executor é
`scripts/migrar.py` — aplica os `*.sql` em ordem de nome, cada um em **uma transação**,
com o registro em `schema_migrations` dentro da mesma transação. Rodar duas vezes é
inócuo. Arquivo alterado depois de aplicado, migração registrada que sumiu do disco, e
migração nova que ordena antes de uma já aplicada **falham** em vez de seguir.

Migração nunca roda automaticamente em produção, e nunca é executada por agente de IA.

## Túnel

WireGuard ponto a ponto entre os datacenters. O tráfego de replicação não divide interface
nem VLAN com o tráfego de serviço das VMs.
