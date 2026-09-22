# Como trabalhamos

## Spec-driven development

A especificação é a fonte da verdade. O código é derivado dela. O agente de IA implementa
contra um documento revisado, nunca contra uma conversa.

O oposto — conversar com o modelo até funcionar — produz dívida técnica, inconsistência
arquitetural e *intent drift*: o modelo se afasta aos poucos do que você queria, e ninguém
percebe até tarde.

## O ciclo

```
constitution → specify → [REVISÃO] → clarify → plan → [REVISÃO]
             → tasks → analyze → implement → [REVISÃO] → commit
```

Os portões de revisão não são formalidade. Corrigir uma spec custa minutos; corrigir
código já escrito custa horas.

### Com o GitHub Spec Kit

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
specify init . --ai copilot     # ou claude, cursor, gemini...
```

| Comando | Quando |
| --- | --- |
| `/speckit.constitution` | Já está escrita em `.specify/memory/`. Só releia |
| `/speckit.specify` | Começar uma feature nova |
| `/speckit.clarify` | Sempre, antes do plano |
| `/speckit.plan` | Depois de aprovar a spec |
| `/speckit.tasks` | Depois de aprovar o plano |
| `/speckit.analyze` | Antes de implementar |
| `/speckit.implement` | Uma tarefa por vez |

Sem o Spec Kit, o método funciona com os templates em `specs/_template/`.

## Tamanho

**Uma spec por feature.** Nunca uma spec monolítica do sistema — ela cresce até não caber
no contexto e vira impossível de manter.

**Uma tarefa cabe numa sessão de contexto.** Um módulo ou um comportamento, com seus
testes, num diff que você lê inteiro sem cansar.

| Tamanho | Exemplo | Veredito |
| --- | --- | --- |
| Bom | Resolver node-name de um disco pelo alias, com testes | Uma sessão |
| Bom | Máquina de estados do ciclo, sem IO | Muito testável |
| Ruim | "Implementar o agente" | Não cabe em nada |
| Ruim | "Adicionar tipagem no projeto todo" | Diff irrevisável |

## A regra que mais se esquece

**Toda vez que você corrigir o agente ou mexer no código à mão, a spec estava incompleta.**
Atualize a spec antes de seguir. Sem isso ela vira ficção em duas semanas.

## Ritmo

Uma tarefa, um commit, uma revisão sua.

Você é responsável pelo código em produção. Revise de verdade, corrija o que precisa, e só
então commite. Aceitar diff sem ler é como este tipo de projeto acumula bug que só aparece
no dia do desastre.

Resista a rodar `/speckit.implement` na lista inteira de tarefas. Ele faz isso, e a
sensação de progresso é ótima — mas você acaba com dois mil linhas que ninguém revisou.

## Definição de pronto

- [ ] Testes passam, incluindo o comportamento em falha
- [ ] `make check` verde
- [ ] Spec atualizada se algo mudou durante a implementação
- [ ] Diff lido por um humano
- [ ] ADR escrito se houve decisão de arquitetura
