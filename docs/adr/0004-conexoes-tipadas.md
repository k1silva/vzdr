# ADR-0004: Sistemas externos entram como conexões tipadas

**Data:** 2026-09-22
**Status:** aceito

## Contexto

O DR precisa falar com clusters VHI. A modelagem óbvia é um "registro de clusters".

Mas a plataforma vai integrar muito mais: monitoramento, billing, object storage, CMDB,
o que vier. Se cada integração for um conceito próprio no núcleo, adicionar a segunda
significa mexer no núcleo, e a décima vira um emaranhado.

## Decisão

Um registro genérico de **conexões**. Cada conexão é uma instância de um **conector
tipado**, que declara schema de configuração, credenciais, health check e capacidades.
"Cluster VHI" é o primeiro conector, não um conceito especial.

Nenhuma feature abre conexão com sistema externo por fora do registro (P13).

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Registro específico de clusters | Cada integração nova mexe no núcleo |
| Cada feature gere suas conexões | Credenciais espalhadas, ninguém sabe o que está conectado, health check duplicado |
| Plugins carregados em runtime | Complexidade desnecessária agora; conectores no repo bastam |

## Consequências

Fica mais fácil: adicionar integração é escrever um conector. Credenciais num lugar só.
Health check e estado uniformes. A interface deriva o formulário do schema do conector.

Fica mais difícil: uma indireção a mais entre a feature e o sistema externo, e é preciso
declarar capacidades corretamente — pedir uma capacidade inexistente tem que falhar na
resolução, não em tempo de uso.
