# Deploy

| Componente | Onde roda | Como |
| --- | --- | --- |
| API e agendador | Fora dos dois clusters | Container ou systemd |
| Agente | Cada hypervisor do DC-1 | systemd, veja `systemd/` |
| Receptor | VM no DC-2 | systemd, uma unidade `qemu-nbd` por volume espelho |
| PostgreSQL | Junto da API | Gerenciado ou container |

## Antes de cada deploy

Lista curta, e cada linha existe porque o preço dela só aparece no deploy — e nada no
repositório percebe um deploy. Item registrado só no documento onde nasceu fica esperando
alguém lembrar no dia.

- [ ] **Algum tipo de efeito ou de resultado foi removido desde o último deploy?** Então ele
      precisa de caminho de descontinuação antes. Um registro guardado com tipo removido é
      tipo desconhecido para a versão nova, e tipo desconhecido pede **reenvio** — que
      reenviaria para sempre. Antes do primeiro deploy remover é de graça, e foi assim que
      `criar_checkpoint` e `inventariar_hypervisor` saíram
      ([`dr-001`, plano](../specs/dr-001-dominio-ciclo/plan.md)). Depois dele, não.

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

## Transporte

O padrão é **`push`**: o QEMU do hypervisor de origem disca para um `IP:porta` no destino
e escreve por NBD sobre **TLS mútuo**. Não há túnel. O cliente não publica porta de
entrada — precisa só de saída NAT — e o único IP público é o do destino, sob controle do
provedor.

Autenticação é o TLS do NBD em si, em todos os modos: `verify-peer=on` nas duas pontas e
`authz-simple` restringindo o CN do cliente. Regra de firewall por `/32` é segunda camada,
não a primeira.

**WireGuard não roda no hypervisor.** Ele existe apenas no modo `rendezvous-wg`, em VM de
borda com rota estática — nunca alterando rota nem carregando módulo de kernel num host de
cluster suportado pelo fornecedor.

Os cinco modos, quando cada um se aplica e por que o `push` é o padrão estão em
[ADR-0008](../docs/adr/0008-modos-de-transporte.md). O relé dos modos que o usam é
componente separado da control plane: [ADR-0009](../docs/adr/0009-separacao-rele-control-plane.md).

O tráfego de replicação não divide interface nem VLAN com o tráfego de serviço das VMs.
