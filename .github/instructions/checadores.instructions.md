---
applyTo: "tests/invariants/*.py"
---

# Checadores de invariante

Cada arquivo aqui sustenta uma afirmação que algum documento faz. Se um checador ficar
frouxo, tudo que ele protegia cai em silêncio — e silêncio é indistinguível de sucesso.

## O que todo checador precisa ter

- **Teste do caminho de falha**, em `tests/unit/test_<nome>.py`. Checador sem teste que o
  veja reprovar é cobertura aparente.
- **Um teste que afirma a propriedade sobre este repositório**, para o checador não passar
  por vacuidade.
- **Mensagem de erro que diz o que fazer**, não só o que está errado.

## Bidirecionalidade

Checador de coerência entre documento e realidade é **sempre nos dois sentidos**. Olhar um
lado fecha metade da classe e dá a sensação de ter fechado inteira — já aconteceu três
vezes aqui.

## Listas de exceção

Evite. Quando existirem, cada entrada carrega justificativa no próprio código, e exceção
que ninguém usa reprova o build. Exceção com data de validade é pior: renovação vira
carimbo.

## Derivar, não enumerar

Conjuntos vêm do repositório sempre que possível — domínios de evento saem de
`packages/*/src/**/py.typed`, pacotes restritos saem de quem declara `py39`. Lista à mão é
lista que desatualiza.
