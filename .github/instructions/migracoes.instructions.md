---
applyTo: "deploy/migrations/*.sql"
---

# Migrações

O esquema é onde as garantias deste projeto moram. Antes de sugerir qualquer coisa aqui,
leia `specs/core-001-tenancy/spec.md`.

## Regras com checador

- **`tenant_id` em toda tabela que guarda dado de tenant** (P9). A lista de exceções é
  **fechada** e vive na spec; `tests/invariants/check_tenant_id.py` reprova exceção que não
  esteja lá, e também exceção que nenhuma migração usa. Acrescentar entrada ao checador sem
  alterar a spec é violação, não configuração.
- Toda tabela com `tenant_id` tem RLS **habilitada e forçada** (ADR-0006). `FORCE` não é
  detalhe: sem ele o dono da tabela ignora a política, e o dono é quem roda as migrações.

## O que esperar de uma migração aqui

- Chave estrangeira composta é usada de propósito para tornar invariantes **impossíveis de
  violar**, não para "integridade" genérica: `(sessao_pai_id, expira_em)` garante que sessão
  derivada expire junto da mãe; `(usuario_id, tenant_id)` garante que perder o papel derrube
  sessão e token.
- Auditoria é *append-only* para a aplicação: `select` e `insert`, nunca `update` nem
  `delete`. E **não** tem chave estrangeira para usuário: registro histórico precisa
  sobreviver à remoção do que referencia.
- Comentário longo explicando o porquê é o padrão, não excesso.

## Nunca

- Migração que apaga dado sem confirmação humana explícita (P6).
- Coluna `tenant_id` nulável: uma consulta filtrada descartaria ou incluiria a linha em
  silêncio, conforme o `WHERE`.
