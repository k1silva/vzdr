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

## O cofre: envelope, e o que ele não protege

Esta é a decisão mais pesada da spec. O banco vai guardar conta de serviço OpenStack que
**cria e apaga VM na nuvem de um cliente**. Não é mais um segredo — é a coisa de maior
valor no sistema.

A pergunta original — "cofre próprio com chave derivada, ou cofre externo?" — junta três
decisões, e a do meio desmonta a formulação: **derivada de quê?** Se de algo que está no
banco, não é cifragem, é ofuscação, e a spec estaria descrevendo proteção que não existe.

### Envelope

| Camada | O quê | Onde vive |
| --- | --- | --- |
| Credencial | A conta de serviço do cliente | Cifrada na tabela do cofre |
| **DEK** | Uma chave por credencial | Cifrada pela KEK, ao lado do dado |
| **KEK** | A chave-mestra | **Fora do banco** — variável de ambiente ou arquivo de permissão restrita na v1; KMS ou Vault depois, sem mudar o esquema |

Rotacionar a KEK reembrulha **só as DEKs**. Sem o envelope, rotacionar significaria
reescrever toda credencial de todo cliente numa janela — e por isso nunca aconteceria.

### Rotacionar KEK e rotacionar credencial são coisas diferentes

| Operação | O que muda | Quem faz |
| --- | --- | --- |
| Rotação de **KEK** | Higiene de cripto: as DEKs são reembrulhadas, as credenciais não mudam | A plataforma |
| Rotação de **credencial** | A conta de serviço muda **no OpenStack do cliente** | O cliente; a plataforma só acompanha |

Confundir as duas faz alguém achar que rotacionou o que não rotacionou.

### O campo é de escrita

Quem cadastrou pode **substituir**, nunca **ler de volta**. Não existe caso de uso legítimo
para a plataforma devolver a senha do cliente, e existir o caminho é existir o vazamento.

### Credencial não aparece em lugar nenhum, e isso é teste

Nem em log, nem em exceção, nem em *traceback*, nem em auditoria. Biblioteca de cliente
OpenStack costuma pôr o payload de autenticação dentro da exceção — é assim que uma
credencial cifrada em repouso vaza em texto puro num agregador de erro.

Não é disciplina: é teste. Provocar falha de autenticação e afirmar que o segredo não
aparece em nada que saia do processo.

### Pré-condição: a custódia da KEK existe antes da primeira credencial real

**Perder a KEK é perder todas as credenciais.** E recadastrar **não** é o plano de
recuperação — pense no que ele significa: ligar para cada cliente e pedir que digite de
novo a credencial que dá acesso à nuvem dele. Não é procedimento, é o anúncio público de
que o provedor perdeu as chaves dos clientes. Para um produto de DR, isso é pior que a
indisponibilidade que causou.

O plano de recuperação é **cópia de guarda**. A KEK é um segredo pequeno, e guardá-la
direito é barato e é prática padrão: fora de linha, lacrada, com **dois custodiantes** e
procedimento de resgate **escrito e testado**. O que não pode existir é uma cópia só, num
host, e a esperança de que ele não morra.

> **Gatilho, nomeado de propósito:** nenhuma credencial de cliente real é armazenada antes
> de o procedimento de custódia existir. Laboratório pode rodar sem; cliente não.

É procedimento humano e não tem checador. Nomear o gatilho é o que faz acontecer.

O `kek_id` por linha é o que torna isso extensível: várias KEKs coexistindo é o mesmo
mecanismo da rotação, e já está no esquema.

**E é assim que a pergunta vai chegar.** A revisão de segurança de qualquer cliente sério
pergunta: *o que acontece se vocês perderem a chave que protege minhas credenciais?*

| Resposta | Resultado |
| --- | --- |
| "O senhor recadastra" | Reprova na hora |
| "Custódia com dois guardiões e procedimento de resgate testado" | Passa |

### O que isto não protege

Cifragem em repouso protege contra **backup vazado, réplica vazada e leitura indevida da
tabela**. Não protege contra quem tem a KEK e o banco ao mesmo tempo — que é o operador da
plataforma.

Isso fica escrito, e não implícito, porque a diferença entre as duas coisas é o que alguém
vai precisar saber ao responder a um cliente.

## Health check: sob demanda em M0

Verificação periódica precisa de agendador, e agendador é `core-003`, marco M1. Esta spec é
M0. Sem separar, ou ela não fecha no marco, ou alguém escreve um agendador improvisado
dentro dela.

Em M0 a verificação é **sob demanda**, e "sob demanda" não é "antes de cada chamada" — isso
dobraria o custo de toda operação. São três momentos:

| Quando | Por quê |
| --- | --- |
| No cadastro | A conexão nasce verificada ou nasce `não verificada`, e o operador sabe na hora |
| Antes de **operação cara** — provisionar, semear | Falhar no meio custa caro; falhar antes custa um round-trip |
| Na falha, revalidando | Chamada de rotina usa a credencial e descobre o problema ao usá-la |

O periódico entra com a `core-003`, e aí o intervalo é configurável por conexão.

## A fronteira de teste

A constituição proíbe mockar libvirt e QMP em teste de integração, e ela está certa. Mas
essa proibição é sobre as **bordas do QEMU**, onde o comportamento que importa mora — e
isso é o agente, `dr-002` e `dr-003`.

**O conector `vhi` não fala libvirt nem QMP.** Ele fala HTTP com Keystone, Nova, Cinder e
Neutron. São fronteiras diferentes, e tratá-las como a mesma coisa é o que faz a discussão
"isso é mock?" voltar a cada revisão.

| Camada | O que se testa | Onde | Com quê |
| --- | --- | --- | --- |
| Tradução de protocolo | Schema, resolução de capacidade, mapeamento de erro, forma da requisição | `tests/unit` | Respostas gravadas |
| Integração | Que o cluster responde como a gravação diz | `tests/integration` | Cluster de laboratório |

### Gravação envelhece, e isso é modo de falha

Resposta gravada tem um defeito próprio: **a API muda e a gravação não**. O teste continua
passando contra uma ficção, e vira mais uma forma de cobertura aparente — categoria que
este repositório já catalogou em quatro formas.

Então toda gravação é um **instantâneo com data e origem**: de qual cluster veio, quando.
E quem detecta a deriva é a suíte de integração contra cluster real, não a de unidade.

## Capacidade é o fato; versão é o proxy

Registrar "Nova 2.89" não diz se o que o produto precisa existe. Registrar "suporta X, Y,
Z" diz. O conector faz **as duas coisas, com papéis diferentes**: checa capacidades, que é
o que decide, e registra versões, que é o que explica.

O que ele faz quando muda:

| Mudança | Resposta |
| --- | --- |
| Versão nova, capacidades intactas | **Avisa e registra.** Não para replicação de ninguém |
| Capacidade de que o produto depende **desaparece** | **Bloqueia**, com o nome da capacidade que sumiu |

É isso que transforma "upgrade de VHI" de risco listado em evento observado.

O que o conector vê são **microversões de API** — Keystone, Nova, Cinder. O que o agente vê
são libvirt e QEMU: **9.5 e 8.2 na origem, 10.2 no receptor**, no laboratório de setembro.
Essa metade é da `core-004`, e a spec de lá precisa do mesmo tratamento, ou o par fica meio
feito.

## O que o laboratório já respondeu

Duas armadilhas de 2026-09-18 e 2026-09-23 são desta spec, e o conector nasce sabendo:

**Ciclo de vida de VM sai pela API, nunca por `virsh`.** Num cluster gerenciado pelo Nova,
ligar uma VM por `virsh` faz o `nova-compute` detectar a divergência de *power state* e
**matar a VM**. É regra do conector, não do agente.

**O fork tem API proprietária.** A Virtuozzo removeu o `backup-begin` upstream e pôs
`x-block-snapshot-create`, `x-block-export-start` e `x-block-checkpoint-remove`. Isso muda o
que o conector pode declarar como capacidade, e é mais uma razão para capacidade ser
checada e não deduzida da versão.

As outras armadilhas do laboratório — `node-name` efêmero, `bitmap-mode: on-success`,
`--quiesce` inexistente neste fork, `raw` recusando checkpoint — são do **agente**, e estão
em [`docs/01-arquitetura-dr.md`](../../docs/01-arquitetura-dr.md). Trazê-las para cá seria
pôr fato no lugar errado.

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
- Credencial nunca em tabela comum, nunca em log, nunca em evento, nunca em exceção,
  nunca em *traceback*, nunca em auditoria — **com teste**, não com disciplina.
- A chave que cifra não vive no banco que guarda o cifrado. Se viver, é ofuscação.
- O campo de credencial é de escrita: substitui-se, não se lê de volta.

## Critério de aceite

- [ ] Registrar uma conexão `vhi`, testar e ver o resultado
- [ ] Credencial não aparece em nenhuma consulta à tabela de conexões, com teste
- [ ] Pedir capacidade inexistente falha na resolução, com teste
- [ ] Um segundo conector fictício é adicionado num teste sem tocar no núcleo
- [ ] Health check falho emite evento e muda o estado
- [ ] Falha de autenticação não deixa o segredo aparecer em log, exceção, *traceback* nem
      auditoria — provocada, não suposta
- [ ] Ler a credencial de volta pela API não é possível: o caminho não existe
- [ ] Rotacionar a KEK mantém toda credencial utilizável, sem reescrevê-las
- [ ] Capacidade que o produto exige e some bloqueia; versão nova que não tira nada só avisa
- [ ] Toda resposta gravada tem data e cluster de origem

## Fora de escopo

Os conectores além do `vhi`. Rotação automática de credencial. Descoberta de recursos —
isso é `core-005`, inventário.

## Perguntas em aberto

As duas originais estão respondidas acima — a do cofre virou "envelope, com a KEK fora do
banco", e a do health check virou "sob demanda em M0, periódico com a `core-003`". O que
sobra:

- [ ] Qual KMS ou Vault na v2. Não bloqueia: o envelope foi desenhado para trocar o guardião
      da KEK sem mexer no esquema.
- [ ] Intervalo padrão do health check periódico — decisão da `core-003`, que traz o
      agendador.
- [ ] Onde ficam as gravações de resposta e como são regeneradas contra o laboratório. É
      questão de ferramenta, e cabe no plano.

### Eventos

Esta spec **ainda não declara eventos**, de propósito. `tests/invariants/check_eventos.py`
exige que evento declarado tenha emissor e teste, então uma tabela `Eventos` escrita antes
da implementação reprovaria o build.

Os eventos previstos estão na `tasks.md`, como intenção, e viram tabela `Eventos` **na
tarefa que os emite**. É a ordem que o checador impõe, e ela é a certa: contrato publicado
é contrato que alguém já pode consumir.
