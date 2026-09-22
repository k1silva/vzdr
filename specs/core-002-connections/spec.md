# core-002 — Conexões e conectores

**Status:** rascunho
**Marco:** M0
**Depende de:** core-001

## Problema

A plataforma vai falar com muitos sistemas externos: clusters VHI primeiro, depois
monitoramento, billing, object storage, o que vier. Se cada feature abrir sua própria
conexão, as credenciais se espalham, ninguém sabe o que está conectado, e adicionar uma
integração nova significa mexer no núcleo toda vez.

## Resultado esperado

Um registro único de **conexões**. Cada conexão tem um **tipo de conector**, que declara
seu schema de configuração, como autentica, como testa saúde e o que sabe fazer.

"Cluster VHI" é o primeiro conector. Adicionar o segundo é escrever um conector, não
alterar o núcleo.

## Modelo

| Conceito | O que é |
| --- | --- |
| Conector | O *tipo*: `vhi`, `zabbix`, `s3`... Declara schema, capacidades e health check |
| Conexão | Uma instância configurada de um conector, pertencente a um tenant |
| Credencial | Guardada no cofre, nunca na tabela de conexão |
| Capacidade | O que aquele conector sabe fazer (`compute`, `block-storage`, `metrics`...) |

## Comportamento normal

1. O operador escolhe um tipo de conector e preenche o formulário derivado do schema dele.
2. As credenciais vão para o cofre; a conexão guarda só a referência.
3. A plataforma testa a conexão e registra o resultado e o horário.
4. Uma feature pede ao núcleo um cliente para a conexão X, declarando a capacidade que precisa.
5. O núcleo devolve o cliente, ou recusa se o conector não tem aquela capacidade.

## Conector `vhi` — capacidades iniciais

`compute`, `block-storage`, `network`, `identity`. Configuração: URL do Keystone, projeto,
domínio, usuário e senha. Health check: autenticar e listar um recurso.

## Comportamento em falha

| Falha | O que acontece | Estado resultante |
| --- | --- | --- |
| Credencial inválida no cadastro | Conexão salva como `não verificada`, erro cru exibido | Cadastrada, inutilizável |
| Sistema externo fora do ar | Health check falha, conexão marcada `degradada`, evento emitido | Features veem o estado |
| Feature pede capacidade que o conector não tem | Erro em tempo de resolução, nunca em tempo de uso | Falha cedo e clara |
| Credencial rotacionada por fora | Health check detecta, alerta | `degradada` até atualizar |

## Invariantes

- **P13:** nenhuma feature abre conexão com sistema externo por fora deste registro.
- **P8:** o erro do sistema externo é preservado cru, não traduzido.
- **P9:** conexão pertence a um tenant.
- Credencial nunca em tabela comum, nunca em log, nunca em evento.

## Critério de aceite

- [ ] Registrar uma conexão `vhi`, testar e ver o resultado
- [ ] Credencial não aparece em nenhuma consulta à tabela de conexões, com teste
- [ ] Pedir capacidade inexistente falha na resolução, com teste
- [ ] Um segundo conector fictício é adicionado num teste sem tocar no núcleo
- [ ] Health check falho emite evento e muda o estado

## Fora de escopo

Os conectores além do `vhi`. Rotação automática de credencial. Descoberta de recursos —
isso é `core-005`, inventário.

## Perguntas em aberto

- [ ] Cofre próprio no banco com chave derivada, ou integração com cofre externo?
- [ ] Health check em que intervalo? Configurável por conexão?
