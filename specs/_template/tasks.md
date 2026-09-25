# <id> — Tarefas

Cada tarefa cabe numa sessão de contexto e vira um commit.

- [ ] **T1** — <descrição>
  - Testes: <o que prova>
  - Arquivos: <onde>
- [ ] **T2** —

## Ordem

T1 → T2. Dependências explícitas quando houver.

## Eventos previstos

**Intenção, não contrato.** Nome de evento é contrato público (ADR-0005): quando a tabela
`Eventos` da spec é preenchida, quem consome webhook já pode depender dele. Publicar antes
de existir é prometer.

Por isso os eventos nascem aqui, e a passagem para a spec acontece **na tarefa que os
emite** — é a ordem que `check_eventos.py` impõe, e ela é a certa.

| Evento previsto | Tarefa que o emite |
| --- | --- |
| `dominio.acao_no_passado` | T<n> |

## Fora desta lista

O que ficou para outra spec.
