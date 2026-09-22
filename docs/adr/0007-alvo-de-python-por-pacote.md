# ADR-0007: O alvo 3.9 é por pacote, não do projeto

**Data:** 2026-09-22
**Status:** aceito

## Contexto

O scaffold fixou `target-version = "py39"` na raiz e descreveu o projeto inteiro como 3.9.
A premissa por trás disso é real, mas mais estreita do que a regra: 3.9 é a versão dos
hypervisors, e no hypervisor roda **o agente**, nada mais.

O control plane — API, CLI, motor de trabalho, tenancy — roda onde nós escolhemos
(ADR-0003: o plano de controle roda fora dos dois clusters). Ali, 3.9 não é restrição
herdada de ninguém: é custo autoimposto. Perde-se `match`, `X | Y` em anotação, tipos
genéricos nativos e o que vier depois, em código que jamais verá um hypervisor.

A conta fica pior com o tempo: 3.9 saiu do suporte upstream, e cada dependência nova do
control plane passa a ser filtrada por uma restrição que não se aplica a ela.

## Decisão

A restrição de 3.9 vale por pacote, para o que roda no hypervisor: `packages/agent` e o
fecho de dependências dele — hoje `packages/core-domain`.

- Cada pacote restrito declara `target-version = "py39"` no próprio `pyproject.toml`,
  estendendo a raiz. A raiz é `py311`.
- `mypy` roda duas vezes: global em 3.11, e uma segunda passada sobre os pacotes
  restritos. Não há alternativa de configuração: `python_version` é opção global do mypy,
  não aceita seção por módulo. Essa segunda passada usa `--python-version 3.10`, e não
  3.9, porque o mypy atual recusa 3.9 por ser antigo demais — é a mesma concessão que o
  AGENTS.md já previa, e não enfraquece nada: **quem verifica a sintaxe de 3.9 é o
  `ruff`**, com `target-version = "py39"`. O mypy ali serve para tipos, não para sintaxe.
- `tests/invariants/check_alvo_py39.py` falha o build se um pacote restrito importar um
  pacote sem a restrição, e também se um pacote que roda no hypervisor perder o `py39`.
- Um job de CI instala **Python 3.9 de verdade** e roda `python -m compileall` sobre os
  pacotes restritos.

Essa última linha é a que importa, e vale ser explícito sobre a divisão de trabalho:

| Camada | O que garante |
| --- | --- |
| `ruff` com `py39` | Primeira linha: pega a maioria da sintaxe 3.10+ no editor e no lint |
| Checador do fecho | Impede que um pacote restrito importe um irrestrito |
| `compileall` em 3.9 real | **A garantia de fato**: o interpretador 3.9 aceita o arquivo, ou não |

Só o `ruff` não basta. Ele não falha, por exemplo, em `X | Y` numa anotação avaliada em
runtime, e regra de lint é heurística sobre texto — o interpretador é o árbitro. Sem o job,
"queremos 3.9" seria intenção declarada, não propriedade verificada. Com ele, a primeira
sintaxe nova que escapar do lint quebra o build antes de quebrar um hypervisor.

O conjunto de pacotes restritos não é uma lista escrita no checador: sai de quem declara
`py39` no pyproject. Uma fonte só.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Manter 3.9 no projeto inteiro | Paga a restrição dos hypervisors em código que nunca roda neles, e a conta cresce a cada dependência nova |
| Subir tudo para 3.11 | O agente quebra no hypervisor em tempo de import, e o erro aparece na produção do cliente, não na CI |
| Restrição só documentada, sem checador | É o estado que esta decisão corrige: fronteira sem verificação é comentário. `core-domain` é justamente o pacote que mais tende a crescer, e cada import novo nele é uma chance de vazar |
| Empacotar o agente com o interpretador (PyOxidizer, container) | Resolveria de vez, mas muda o modelo de deploy do agente no hypervisor — decisão maior, que não cabe em `core-001` |

## Consequências

Fica mais fácil: o control plane usa a linguagem inteira. `core-001` em diante — tenancy,
API, jobs — não precisa mais de `Optional[X]` por obrigação.

Fica mais difícil: existem dois alvos no repositório, e é preciso saber em qual pacote se
está. Duas coisas tornam isso verificável em vez de decorado — o `pyproject.toml` de cada
pacote restrito diz o alvo na cara, e o checador falha antes do merge.

E há uma fronteira nova para respeitar: **o que roda no hypervisor só importa o que é 3.9**.
Se um dia o agente precisar de algo do núcleo que não seja `core-domain`, a escolha é
explícita — ou o pacote entra no fecho e aceita a restrição, ou a conversa passa a ser pela
API, que é o que P7 e a fronteira "o agente não fala com o banco" já mandam.
