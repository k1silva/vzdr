# ADR-0001: Monolito modular

**Data:** 2026-09-22
**Status:** aceito

## Contexto

A plataforma terá várias features (DR primeiro, depois backup, monitoramento,
provisionamento). A tentação é separar cada uma em serviço próprio desde o início.

Somos uma equipe pequena, sem escala que justifique operação distribuída, e ainda não
sabemos onde as fronteiras entre features realmente caem.

## Decisão

Monolito modular: um deploy, fronteiras de domínio mantidas por estrutura de pacotes e
checadores na CI. O agente que roda nos hypervisors é a única exceção.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Microserviços por feature | Custo de rede, observabilidade e deploy antes de ter escala; fronteiras ainda não validadas |
| Monolito sem módulos | Não permite extrair nada depois; a segunda feature vira remendo |

## Consequências

Fica mais fácil: desenvolver, testar, depurar, fazer deploy, refatorar fronteiras.

Fica mais difícil: escalar uma feature isoladamente — mas extrair um módulo bem isolado é
trabalho de dias, enquanto reunir microserviços mal fatiados é trabalho de meses.

Exige disciplina: features não conhecem umas às outras (P11), e a CI verifica isso em
`tests/invariants/check_import_boundaries.py`.
