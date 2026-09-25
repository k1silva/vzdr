# Instruções para revisão de código

Leia o `AGENTS.md` na raiz: ele traz os comandos, as convenções e as fronteiras, e vale
como está. Este arquivo cobre só o que falta para revisar bem **este** repositório.

## A fonte das decisões não é o código

Quando uma escolha parecer estranha, ela provavelmente foi decidida e registrada. A ordem
de autoridade é:

1. `.specify/memory/constitution.md` — treze princípios inegociáveis, citados como `P1`…`P13`.
   Em conflito com qualquer outro documento, a constituição vence.
2. `docs/adr/` — decisões de arquitetura, com contexto, alternativas e consequências.
3. `specs/<id>/spec.md` — a fonte da verdade de cada feature.
4. `docs/pendencias.md` — o que está aberto, com dono e data.

**Se for contradizer uma decisão registrada, cite o documento.** "Isto contraria o ADR-0006,
que decidiu X porque Y" é revisão útil; "considere usar Z" sobre algo já decidido é ruído,
e faz quem lê procurar o contexto que você tinha e não mostrou.

Se **não encontrar** documento para algo que parece deliberado, diga isso — decisão
intencional sem razão escrita é achado, não falso positivo.

## O que este projeto considera um problema grave

Estas categorias vêm de erros reais cometidos aqui, e são o que mais vale apontar:

- **Cobertura aparente.** Teste que passa sem testar o que parece testar; guarda que
  ninguém chama; ramo que nenhum teste alcança; verificação cujo resultado não chega a
  quem decide. Já apareceu em cinco formas.
- **Um sentido só.** Checador que olha uma direção de uma relação bidirecional fecha
  metade da classe e dá a sensação de ter fechado inteira.
- **Caminho que nunca executa onde se testa.** Ramo que só roda em estado que o ambiente
  de teste nunca tem.
- **Erro que não distingue causas.** `except` largo que transforma um problema em outro
  no diagnóstico.
- **Valor que precisa ser igual a outro.** Parâmetro, coluna ou cópia que pode discordar
  da fonte.
- **Regra que depende de alguém lembrar.** Preferimos tornar o errado irrepresentável a
  detectá-lo: restrição no esquema em vez de checagem no código, uma porta só em vez de
  convenção.

## Convenções que não são descuido

- **Termos de negócio em português, o resto em inglês.** `papel_concedido`, `ciclo`,
  `ponto_de_recuperacao` são propositais. Nome de evento é `dominio.acao`, com domínio em
  inglês (é o módulo) e ação em português (é negócio) — ver ADR-0005. Não sugira
  traduzir nem padronizar o idioma.
- Mensagens de commit e documentos são em português.
- Classe de exceção termina em `Error`, com o termo de negócio em português.
- O alvo de Python é **3.11**, exceto `packages/agent` e `packages/core-domain`, que são
  **3.9** porque rodam no hypervisor (ADR-0007). Sugestão de sintaxe 3.10+ nesses dois
  está errada.

## Onde olhar com mais atenção

- `deploy/migrations/*.sql` — esquema é onde as garantias moram neste projeto.
- `tests/invariants/` — os checadores; se um deles ficar frouxo, tudo que ele protegia cai.
- Qualquer coisa que toque credencial, sessão, token ou `tenant_id`.

## O que não apontar

- Ausência de type hints em testes.
- Comentários longos: eles carregam o porquê de propósito, e o porquê é o que se perde.
- Sugestão de extrair função por tamanho, sem argumento de correção ou de leitura.
