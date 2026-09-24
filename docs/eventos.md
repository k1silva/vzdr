# Eventos

> **Gerado** por `tests/invariants/check_eventos.py`. Não edite à mão: o
> checador reprova se este arquivo divergir das specs.

A fonte de cada evento é a seção `Eventos` da spec da feature que o emite.
Esta página só reúne as fontes para quem consome webhook conseguir ler tudo
de uma vez.

| Evento | Quando | Declarado em | Emitido em |
| --- | --- | --- | --- |
| `tenancy.concessao_negada` | Tentativa de conceder papel sem ser `admin` daquele tenant | `specs/core-001-tenancy/spec.md` | `packages/core-tenancy/src/vzdr/core/tenancy/papeis.py` |
| `tenancy.papel_autoconcedido` | Quem concede e quem recebe são o mesmo principal. Tipo próprio para permitir alerta sem varrer o log | `specs/core-001-tenancy/spec.md` | `packages/core-tenancy/src/vzdr/core/tenancy/papeis.py` |
| `tenancy.papel_concedido` | Papel concedido ou alterado dentro de um tenant. Na criação do tenant, o autor é o operador de plataforma | `specs/core-001-tenancy/spec.md` | `packages/core-tenancy/src/vzdr/core/tenancy/papeis.py`, `packages/core-tenancy/src/vzdr/core/tenancy/plataforma.py` |
| `tenancy.plataforma_iniciada` | Primeiro operador de plataforma criado pelo bootstrap. Único ato do sistema sem autor autenticado | `specs/core-001-tenancy/spec.md` | `packages/core-tenancy/src/vzdr/core/tenancy/plataforma.py` |
| `tenancy.tenant_criado` | Tenant criado pelo operador de plataforma, já com o primeiro `admin` | `specs/core-001-tenancy/spec.md` | `packages/core-tenancy/src/vzdr/core/tenancy/plataforma.py` |
| `tenancy.tenant_trocado` | Sessão emitida para outro tenant a partir de uma válida, sem senha | `specs/core-001-tenancy/spec.md` | `packages/core-tenancy/src/vzdr/core/tenancy/sessao.py` |
