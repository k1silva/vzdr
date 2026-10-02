# dr-001 — Plano técnico

**Spec:** ./spec.md

## Abordagem

Tudo em `vzdr.core.domain`, que é puro e está sob `mypy --strict`. Nenhuma linha aqui toca
libvirt, QMP, banco ou rede — o checador de pureza já recusa, e é ele que mantém o critério
de saída do M1 possível.

O módulo se divide em três, pela razão de mudar:

| Módulo | O que é | Muda quando |
| --- | --- | --- |
| `ciclo.py` | Estados, transições, a função da máquina | O fluxo do ciclo muda |
| `efeitos.py` | Os efeitos e os resultados, como valores | O contrato com o agente muda |
| `saude.py` | `degradada`, idade do ponto, janelas pendentes | A política de RPO muda |

### A forma da máquina

```python
def iniciar(tenant_id, ciclo_id, vm_id, discos, no_de_origem, agora: datetime) -> Transicao
def avancar(estado: EstadoDoCiclo, entrada: Optional[Resultado], agora: datetime) -> Transicao
def abandonar(estado: EstadoDoCiclo, agora: datetime) -> Transicao
```

`Optional`, e não `Resultado | None`: `core-domain` é alvo 3.9 pelo
[ADR-0007](../../docs/adr/0007-alvo-de-python-por-pacote.md), e quem garante a sintaxe é o
`ruff`, não o `mypy`. Vale para todo código desta spec.

`Transicao` traz o estado novo e os efeitos a pedir. **Função, não objeto com métodos**: o
estado entra e sai, nada é guardado. É o que torna um teste uma linha e um cenário de falha
uma lista de resultados.

**Um tipo de retorno para toda entrada, e "terminou" é campo.** A entrada `None` é o
agendador deixando o tempo correr. "Nada aconteceu" — `None`, resultado de outro ciclo,
resultado repetido, ciclo já terminado — é uma `Transicao` com o mesmo estado e zero
efeitos. "Terminou" é `estado.desfecho`, e **nunca** se deduz de zero efeitos: um ciclo que
espera também não pede nada, e um que termina pode pedir limpeza (T6). O chamador não
distingue dois tipos de retorno e não confunde os dois casos. Decidido ao escrever a
assinatura, e não no décimo caso.

**O desfecho é `saude.Desfecho`, e não há outro.** `ciclo.py` não define enum de desfecho:
um tipo próprio seria o mesmo conceito nascendo duas vezes — o erro da `degradada` entre a
`dr-006` e esta spec —, e uma tabela de tradução precisaria de teste para não divergir. Sem
tipo próprio, não há onde escrever desfecho sem par. Nos dois sentidos, por estrutura: o
campo é tipado `Desfecho` e o módulo não define enum além de `Fase`
(`tests/unit/test_ciclo.py::test_o_desfecho_do_ciclo_e_o_de_saude`), e todo valor de
`Desfecho` é produzido por algum caminho (`tests/unit/test_ciclo.py::test_todo_desfecho_e_alcancavel`).

**O desfecho de quem para no meio sai dos fatos, e não da fase.** `abandonar` é o único
lugar que o decide: ponto já registrado → `CONCLUIDO` (o resíduo vai para a T7); resíduo sem
ponto → `FALHOU`; nem um nem outro → `NUNCA_INICIOU`. Todo resultado que não é sucesso
passa por ele — e a T6 acrescenta ali os efeitos de limpeza e o prazo.

**Três relógios, e o estado carrega dois.** `iniciado_em` (duração do ciclo, telemetria) e
`fase_desde` (base do prazo da fase, T6). `fase_desde` só muda ao **entrar** numa fase: o
tempo passar não começa fase nenhuma. O terceiro, o ponto mais recente, é da **VM** e não do
ciclo: atravessa ciclos, e um ciclo que nunca iniciou tem que deixá-lo envelhecer. Mora com
quem calcula a idade (`saude.idade_do_ponto`). O ciclo só diz quando registrou o **seu**
ponto (`ponto_registrado_em`).

**Três leituras que a T5 decidiu, e que T6/T7 podem refinar:**

- **Migração detectada** (nó do Nova ≠ nó gravado): o ciclo termina sem pedir nada, com
  `NUNCA_INICIOU` — nada foi escrito — e `migracao_detectada` verdadeiro. **Isto é o
  ADR-0012, decisão 1, que o [ADR-0016](../../docs/adr/0016-confianca-no-bitmap.md)
  substituiu**: o nó é procurador que erra nos dois sentidos, e a confiança passa a ser
  lida do próprio bitmap. Vale no código até a T9 e a T6. O executor do resync é da
  `dr-003`, que não existe, e nenhum consumidor lê `migracao_detectada` hoje. O que a T5 garante é
  que o próximo ciclo não erra em silêncio: `no_do_proximo_ciclo` recusa, porque os dois nós
  candidatos estão errados — o gravado faz o laço de `NUNCA_INICIOU`, o encontrado copia
  com bitmap que atravessou evento de host. O risco que sobra está na tabela de Riscos.
- **Inventário com job em curso**: o ciclo não começa por cima de um job. Abandona na
  leitura, `NUNCA_INICIOU`; o que fazer com o job é da reconciliação, e o laço que isso
  forma até a T7 está na tabela de Riscos.
- **A T5 usa metade do inventário.** Decide só por `job_em_curso`. Os nomes ficam no estado,
  crus (`nomes_no_inventario`): classificá-los pelos três estados do `ler_nome` e achar
  órfãos é da T7. Guardá-los é barato, e descartá-los mataria a evidência dentro de
  `avancar`.
- **`ResultadoDeCopia` com `concluido` falso**: resultado é resposta final, e não relatório
  de progresso. Cópia que respondeu sem concluir não concluiu.

O [ADR-0015](../../docs/adr/0015-efeito-como-valor.md) decide a forma do efeito; este plano
só a executa.

### A varredura do envelope, feita uma vez

O contrato do efeito foi emendado quatro vezes — `ciclo_id`, chave de exclusão, `alvo`,
preempção — e as quatro responderam **a mesma pergunta**: *o que a fila, o despachante e a
reconciliação precisam ler de um efeito sem abrir o que ele significa?* Cada rodada
respondeu um pedaço porque o pedaço foi descoberto.

Esta é a passada única, feita antes da T3 para transformar uma sequência aberta de emendas
numa fechada. Cada item vira campo, ou vira decisão registrada de que **não** é campo.

| O que o envelope precisa | Decisão | Por quê |
| --- | --- | --- |
| De que tenant é | **campo** `tenant_id`, e o **único** lugar onde tenant é dito | P9. A fila isola sem abrir o efeito. Nenhum corpo repete tenant ou referência de onde derivá-lo: duas expressões podem discordar, e com RLS uma delas vira oráculo de existência |
| De que ciclo é | **campo** `ciclo_id` | Propriedade 3: descartar resultado atrasado |
| Por onde se alcança quem executa | **campo** `alvo` | Os três caminhos de falha independentes |
| Se conflita com outro efeito | **campo** `chaves_de_exclusao`, uma por disco, nos de disco | Propriedade 4. Excluem-se quando **se intersectam** |
| De quantos discos | **tipo**: `EfeitoDeDisco` (um) ou `EfeitoDeVm` (todos) | Linha acrescentada depois — a varredura perguntou o que a fila lê, e não de quantos discos. Checkpoint e congelamento são da VM, e feitos disco a disco dariam um instante por disco |
| Se pode tomar chave tomada | **categoria** `EfeitoDePreempcao` | Tipo, não *flag*: *flag* é ativável por quem não leu as obrigações |
| Quanto tempo o lease dura | **não é campo** | O heartbeat governa. Valor fixo seria constante derivada de perfil de parque, que a spec proíbe |
| Em que ordem despachar | **não é campo** | Deriva da categoria: preempção antes do resto. Campo de prioridade seria segunda fonte de verdade sobre a mesma coisa |
| Se tolera repetição | **não é campo** | Todo efeito tolera, por contrato. *Flag* permitiria declarar que não tolera, e a fila não tem como honrar isso |
| Quantas tentativas, com que espera | **não é campo** | Política da fila. O domínio é puro e não conhece rede |
| Que nome o efeito cria | **não é campo** | Derivado de `ciclo_id` pelas funções de identidade. Campo seria segunda fonte de verdade |
| Versão do contrato | **não é campo** | Evolução aditiva: campo novo é opcional e nunca muda significado. Versão explícita convidaria a ramificar por versão. **Só é correto porque valor desconhecido de campo de segurança é recusa** — sem isso seria aposta de que todos os consumidores estão na mesma versão |
| O que fazer com valor que não se conhece | **não é campo, é regra** | Campo desconhecido se ignora; valor desconhecido de `alvo`, chave ou categoria se **recusa**, devolvendo o efeito à fila. A distinção é entre informação e regra |
| O que a preempção faz com o detentor da chave | **não é campo, é regra** | **Coexiste.** Preempção não precisa de exclusividade, precisa de permissão para agir apesar da chave — e não é escritor |
| **Sobre o que o efeito é** | **campo** `vm_id`, em todo efeito | Linha acrescentada depois, e é a pergunta que produziu o achado inteiro: a varredura perguntou o que o despachante lê, e **nunca perguntou se o efeito tem sujeito**. Dois efeitos de leitura nasceram sem — um inventário que não dizia de onde, uma consulta que não dizia de quem. Quem guardar efeitos usa chave estrangeira **composta** `(tenant_id, vm_id)`, o padrão da `core-001`: com `vm_id` só, a integridade referencial ignora RLS e vira oráculo de existência |
| **Em qual nó roda** | **campo** `no`, obrigatório no efeito de agente e proibido nos outros | O `Alvo` é por modo de falha, e agentes de nós diferentes falham separado: "agente de origem" sem o nó não é um alvo, são vários. O despachante **não** resolve o nó a partir do `vm_id` — seria ler fora do envelope, e na reconciliação resolver é exatamente o que está em dúvida depois de uma migração. O nó vem **declarado, com procedência** (a última localização que o Nova informou), e é **conferido** na resposta |
| Quem respondeu | **campo** `no_que_respondeu`, no resultado | Resultado de outro nó não responde. E quando o nó é o certo mas a VM já saiu dele, a resposta é `ResultadoVmAusente` — nunca inventário vazio, que seria verdade sobre o nó e mentira sobre a VM |
| O `vm_id` da leitura é chave de exclusão? | **não, e é deliberado** | Com chave, a consulta de evidência só rodaria com o lease livre — e o lease está preso pela cópia zumbi que é a razão de ela existir. Deadlock, e não se resolve com preempção: preempção retira capacidade de escrever, e uma leitura não retira nada de ninguém. Registrado aqui porque o atalho de pôr o `vm_id` na chave "de graça" é tentador, e alguém generalizaria |

**Um ciclo é de uma VM só.** Nenhum documento o afirmava, e três pressupunham: o
`EstadoDoCiclo` tem um `vm_id`; o ciclo "fecha **a** janela", e a janela é o bitmap de uma
VM; o ponto de recuperação é "de todos os volumes de **uma** VM, do mesmo ciclo" (P5).
Fica afirmado aqui. Por isso o `vm_id` do efeito é a VM do ciclo, e `responde_a` compara
o sujeito mesmo que o ciclo já o determine: a igualdade de ciclo protege enquanto a
regra valer, e a de sujeito protege o dia em que alguém a quebrar sem perceber.

**Tipos removidos.** `criar_checkpoint` e `inventariar_hypervisor` deixaram de existir, e
um registro guardado com eles é tipo desconhecido — que pede reenvio, e reenviaria para
sempre. Hoje não há fila nem agente em produção, então remover é de graça. Depois do
primeiro deploy, remover tipo exige caminho de descontinuação, e isso é da `core-003` — com
o gatilho na lista de [antes de cada deploy](../../deploy/README.md), que é o único lugar
consultado no dia em que o preço aparece.

O quarto alvo, `API_DA_NUVEM_DE_DESTINO`, **entrou** — e a frase que dizia "não entra
agora: nenhum efeito da v1 o usa" era falsa desde o começo. O snapshot Cinder que é o ponto
de recuperação é chamada à API da nuvem de destino, e sem ele o ciclo não termina. A regra
continua valendo — valor de enumeração sem efeito que o produza é código morto que parece
desenho —, e foi ela que errou de fato: havia efeito, só que ele faltava na enumeração.
Valor novo de `Alvo` é aditivo: chega numa versão antiga como `ValorDesconhecidoError`, que
pede reenvio.

**A pergunta que a varredura não fez: o conjunto de efeitos executa o ciclo inteiro?** Ela
perguntou coisas sobre cada efeito, e faltavam três no conjunto — `RegistrarPontoDeRecuperacao`,
`RetirarExport` e `RemoverCheckpointsAnteriores`. A resposta agora é mecânica: a tabela
`EFEITOS_DA_FASE` de `ciclo.py`, conferida nos dois sentidos — toda fase emite um efeito,
todo efeito é emitido por uma fase.

`RemoverCheckpointsAnteriores` **não** tem segundo id de ciclo. Ele significa "mantenha só o
checkpoint deste ciclo": com um efeito por checkpoint, as janelas consolidadas dariam vários
efeitos do mesmo ciclo, tipo e chaves, e a resposta de um responderia ao outro. E apagar o
checkpoint do ciclo corrente fica impossível de expressar, porque não há campo onde
escrevê-lo.

### Serialização é parte do tipo, não um detalhe

Efeito e resultado nascem com `para_json` e `de_json`, e o teste de ida e volta é escrito
junto — não depois, quando a fila do `core-003` existir.

O motivo é o do próprio ADR: se a serialização vier depois, ela vai ser moldada pelo que já
foi escrito, e o primeiro efeito que não couber numa linha vai ganhar uma exceção em vez de
um conserto.

### `degradada` não é estado da máquina

É **conta**, e por isso vive em `saude.py`, não em `ciclo.py`:

```python
def esta_degradada(idade: timedelta, rpo: timedelta, fator: float = 2.0) -> bool
```

Nenhuma transição a produz, nenhum campo a guarda. O `fator` é parâmetro com padrão,
porque depende de perfil de parque — e a spec proíbe constante derivada de parque.

**O relógio entra por parâmetro, nunca lido por dentro.** Quem recebe a `idade` já
recebeu o resultado da subtração; nenhuma função deste módulo chama `now()`. Função que lê
o relógio por dentro não é reproduzível, o teste não consegue fixar o instante, e a falha é
silenciosa: ela passa hoje e reprova em outro fuso, em outro segundo, na virada do horário
de verão. Onde a data for necessária como valor, ela é argumento de assinatura pública.

**E `degradada` não vira coluna depois.** Vai chegar o dia de "liste todas as VMs
degradadas" numa consulta, e a saída óbvia vai parecer materializar a coluna por
desempenho. A resposta é *view* ou expressão computada no SQL — a conta, escrita uma vez
mais, na linguagem de lá. Está escrito aqui porque agora é barato: campo que nasce de
pressão de desempenho não volta atrás, e a partir dele existem duas fontes de verdade que
podem discordar. É o mesmo raciocínio que recusou coluna `origem` na auditoria.

### Identidade de ciclo

`nome_do_bitmap(ciclo_id)`, `nome_do_checkpoint(ciclo_id)` e `nome_do_export(ciclo_id, disco)`,
puras e determinísticas. Órfão ganha definição — nome cujo ciclo não está ativo — e a
reconciliação compara conjuntos em vez de casar prefixo.

O export entrou nesta lista pelo cercamento: com nome fixo por disco, um cercamento atrasado
derruba o export do ciclo seguinte em vez do zumbi. Isso emendou o R3 da `dr-006`, que
continua valendo para volume e anexação, que atravessam ciclos.

## Módulos tocados

| Pacote | O que muda |
| --- | --- |
| `packages/core-domain` | `ciclo.py`, `efeitos.py`, `saude.py`, `identidade.py` |
| `tests/unit` | Toda a suíte; nada em `tests/db` nem em `tests/integration` |
| `docs/adr` | ADR-0015, o contrato do efeito |

Nenhuma migração, nenhuma tabela. A persistência do ciclo é do `core-003`, e a spec diz que
conversa com libvirt é da `dr-002` e da `dr-003`.

## Modelo

Sem banco. Os tipos:

```python
class Fase(Enum):          # em ciclo.py, com ETAPAS_DA_FASE
    LOCALIZANDO, VALIDANDO,                  # leituras: abandono sem residuo
    FECHANDO_JANELA, PUBLICANDO, COPIANDO, CONFIRMANDO,
    REGISTRANDO_PONTO, LIBERANDO,            # LIBERANDO em tres etapas ordenadas
    CERCANDO                                 # da reconciliacao, transicoes na T7
# desfecho terminal: saude.Desfecho — nao ha enum de desfecho em ciclo.py

@dataclass(frozen=True)
class EstadoDoCiclo:
    tenant_id: UUID
    ciclo_id: UUID
    vm_id: UUID
    discos: tuple[str, ...]
    no_de_origem: str          # ADR-0012: parte do estado, comparado a cada ciclo
    iniciado_em: datetime
    fase: Fase
    fase_desde: datetime       # so muda ao entrar numa fase
    etapa: int
    pendentes: tuple[Efeito, ...]
    ja_deixou_residuo: bool    # so vira verdadeiro; o desfecho do abandono sai daqui
    no_encontrado: Optional[str]
    ponto_registrado_em: Optional[datetime]
    desfecho: Optional[Desfecho]
# janelas pendentes e telemetria entram com quem as usa: T6 e T8
```

`ja_deixou_residuo` está aqui porque "o abandono deixa resíduo?" é pergunta sobre o
**caminho** do ciclo, e `abandono_deixa_residuo` responde sobre a **fase**. Os dois só
coincidem enquanto nenhuma transição voltar a uma leitura depois de escrever — e a T7 vai
querer voltar: VM que migra no meio do ciclo precisa ser localizada de novo. Com o fato no
estado, ela pode. A alternativa era a máquina proibir essa volta, conferida sobre a tabela de
transições; seria estrutural, mas uma promessa sobre a tabela que a T7 estende, e quem
estende não lê a promessa. O campo é atualizado ao entrar em cada fase, com
`ja_deixou_residuo or abandono_deixa_residuo(fase)`, e nenhuma transição o devolve a falso.

`no_de_origem` está aqui porque o ADR-0012 o tornou parte do estado do ciclo, não porque o
ciclo precise dele para avançar. Comparar o nó atual com o gravado é a primeira coisa que a
máquina faz.

## Interfaces

```python
# efeitos.py — o que a máquina pede
class Alvo(Enum):
    # Criterio: MODO DE FALHA, nao geografia. Dois efeitos tem o mesmo alvo se,
    # quando um e inentregavel, o outro tambem e. Por isso agente e Nova da mesma
    # nuvem sao alvos diferentes — e a evidencia do no depende disso.
    AGENTE_DE_ORIGEM = "agente_de_origem"
    RECEPTORA = "receptora"
    API_DA_NUVEM_DE_ORIGEM = "api_da_nuvem_de_origem"
    API_DA_NUVEM_DE_DESTINO = "api_da_nuvem_de_destino"   # o ponto de recuperacao

@dataclass(frozen=True)
class Efeito:
    ALVO: ClassVar[Alvo]       # da especie, nao da ocorrencia: nao e campo
    tenant_id: UUID            # P9; a fila nao abre o efeito para isolar
    ciclo_id: UUID             # ADR-0015, propriedade 3
    vm_id: UUID                # o sujeito
    no: Optional[str]          # so nos de agente, e obrigatorio neles
    def para_json(self) -> dict[str, Any]: ...

class EfeitoDeDisco(Efeito):
    # ADR-0015, propriedade 4. Sem chave, dois blockdev-backup do MESMO ciclo
    # podem escrever o mesmo espelho — e o ciclo_id nao distingue.
    def chaves_de_exclusao(self) -> tuple[ChaveDeExclusao, ...]: ...   # uma: (vm, disco)

class EfeitoDeVm(Efeito):
    # Age em todos os discos como unidade; segura uma chave por disco, e a fila
    # concede todas de uma vez ou nenhuma.
    def chaves_de_exclusao(self) -> tuple[ChaveDeExclusao, ...]: ...

def se_excluem(a: Efeito, b: Efeito) -> bool: ...   # INTERSECAO, nao identidade

class FecharJanela(EfeitoDeVm): ...   # congela + checkpoint, UMA unidade
class IniciarCopia(Efeito): ...
class DescartarBitmap(Efeito): ...
class ConfirmarNoDestino(Efeito): ...
class InventariarVm(Efeito): ...           # da VM, no no declarado; nunca chave
class ResultadoVmAusente(Resultado): ... # "a VM nao esta neste no"
class EfeitoDePreempcao(EfeitoDeDisco):
    # A unica categoria que toma chave JA tomada — sem isso o cercamento e
    # impossivel, porque a chave esta presa por quem ele vai derrubar.
    # Nunca escreve dado de cliente; e idempotente; o sucesso dele e evidencia.
    ...

class PublicarExport(EfeitoDeDisco): ...      # alvo=RECEPTORA; nome vem do ciclo
class CercarDestino(EfeitoDePreempcao): ...  # alvo=RECEPTORA; mecanica QMP na dr-006

@dataclass(frozen=True)
class Resultado:
    ciclo_id: UUID
    @classmethod
    def de_json(cls, dados: Mapping[str, Any]) -> "Resultado": ...

# ciclo.py — a máquina
def avancar(estado: EstadoDoCiclo, entrada: Optional[Resultado], agora: datetime) -> Transicao
def reconciliar(estado: EstadoDoCiclo, inventario: Inventario) -> Transicao
```

A chave é do tipo, não do protocolo: a fila precisa lê-la para recusar o segundo lease, e
só lê o que o valor carrega. A **liberação** dela não é deste módulo — é evidência, que
chega por `reconciliar`.

`CercarDestino` está na enumeração porque cercar é um efeito, e a máquina decide quando
pedi-lo. O que **não** está aqui é a mecânica: `block-export-del`, o `mode` e o fallback de
reinício do `qemu-storage-daemon` são da `dr-006`, dona do ciclo de vida do export. A
divisão sai da tabela de [`specs/README.md`](../README.md), e a spec a registra.

`reconciliar` é função separada porque a entrada é diferente: não é o resultado de um efeito
pedido, é a fotografia da VM no nó declarado. Fundi-la em `avancar` faria a assinatura aceitar dois
tipos de entrada e a função ramificar no começo.

## Riscos

Toda linha nomeia o **mecanismo** que a mantém verdadeira — teste, checador, medição, ou a
tarefa ainda aberta que vai criá-lo. `tests/invariants/check_afirmacao_tem_mecanismo.py`
confere que cada um existe, e que tarefa feita não continua sendo citada no lugar do
mecanismo.

| Risco | Mitigação |
| --- | --- |
| A invariante da falha cair numa "otimização" | Teste **parametrizado sobre a enumeração de falhas**, afirmando que nenhum caminho produz resync completo. É o teste mais importante do projeto, não só da spec **Mecanismo:** Mecanismo ainda não existe: `T6`. |
| A evidência ser pedida à instância que detém o lease | A consulta vai para o **nó declarado** no envelope e é respondida por quem serve aquele nó, nunca pela instância que detém o lease; resposta de outro nó não responde. Pedir ao detentor é a implementação natural e é a errada **Mecanismo:** `tests/unit/test_efeitos.py::test_resposta_de_outro_no_nao_responde`; a consulta pedida ao nó e não ao detentor, `T7`. |
| A propriedade 4 travar o próprio cercamento | Preempção é categoria nomeada no tipo, com as quatro obrigações. O teste da T7 não passa sem ela **Mecanismo:** `tests/unit/test_efeitos.py::test_so_preempcao_toma_chave_tomada`; a liberação da chave, `T7`. |
| Fila rotear `CercarDestino` para o agente da origem | `alvo` é campo do efeito, não dedução do despachante **Mecanismo:** `tests/unit/test_efeitos.py::test_cada_efeito_no_seu_alvo`, `tests/unit/test_efeitos.py::test_alvo_nao_e_campo_de_instancia`. |
| Efeito da API da nuvem cair no mesmo alvo do agente | O critério do `Alvo` é modo de falha, e está escrito na enumeração. Teste que os separa **Mecanismo:** `tests/unit/test_efeitos.py::test_a_consulta_ao_nova_nao_e_do_agente`. |
| O conjunto de efeitos não executar o ciclo inteiro | **Mecanismo:** `tests/unit/test_ciclo_fases.py::test_todo_efeito_e_emitido_por_ao_menos_uma_fase`, `tests/unit/test_ciclo_fases.py::test_toda_fase_emite_ao_menos_um_efeito`. Faltaram três efeitos, e só apareceram quando alguém enumerou as fases à mão. |
| Migração parar a proteção da VM sem ninguém ver | Depois de migração, o ciclo termina `NUNCA_INICIOU`, fora da taxa de falha, e o próximo ciclo precisa de um nó de origem que não existe antes do resync. Um agendador que carregue o nó gravado entra num laço silencioso de `NUNCA_INICIOU` com 0% de falha; um que carregue o encontrado copia com bitmap inválido. A recusa transforma os dois em erro visível — mas a proteção continua parada até o resync, e o único sinal no painel é `degradada`, a 2× o RPO. **Mecanismo:** a recusa, `tests/unit/test_ciclo.py::test_no_do_proximo_ciclo_recusa_depois_de_migracao`; a troca da comparação de nó pelo estado do bitmap (ADR-0016), que faz migração graciosa deixar de parar a proteção, Mecanismo ainda não existe: `T9` e `T6`. |
| Ciclo de energia do guest deixar nome órfão | Um RUNNING → POWEROFF → RUNNING, sem migração e no mesmo nó, faz o libvirt converter os dirty-bitmaps em bitmaps comuns: os checkpoints somem, os bitmaps ficam, e o backup seguinte falha com "Bitmap already exists" (OpenNebula one#6206). O desenho raciocinava sobre evento de host e migração, e este não é nenhum dos dois. O `ler_nome` de três estados já classifica o nome; recolher é da reconciliação. **Mecanismo:** Mecanismo ainda não existe: `T7`. |
| Cópia que falha deixar o job no ar e parar a proteção em silêncio | `IniciarCopia` falha: `FALHOU`, contado uma vez. O job fica, e o lease com ele. Todo ciclo seguinte vê `job_em_curso` e termina `NUNCA_INICIOU`, fora da taxa — o painel mostra uma falha e depois nada. **Mecanismo:** Mecanismo ainda não existe: `T7`, que libera o job por evidência. |
| Prazo estourado num ciclo que já deixou resíduo virar "nunca iniciou" | O desfecho sai de `ja_deixou_residuo`, fato do caminho que nunca volta a falso, e não da fase corrente — porque uma volta a LOCALIZANDO depois de escrever estaria numa fase sem resíduo com um checkpoint já criado. Trabalho foi tentado, e tirá-lo da taxa de falha a deixaria otimista. **Mecanismo:** `tests/unit/test_ciclo.py::test_nenhuma_transicao_devolve_o_residuo_a_falso` e `tests/unit/test_ciclo.py::test_o_desfecho_sai_do_residuo_e_nao_da_fase`; o prazo em si, `T6`. |
| A resposta por fase divergir dos efeitos que a fase emite | Ela é derivada da tabela, e não enumerada. Isso garante a resposta **por fase**, e só isso: não diz nada sobre o ciclo. **Mecanismo:** `tests/unit/test_ciclo_fases.py::test_residuo_e_derivado_dos_efeitos_e_nao_enumerado`. |
| O envelope crescer de emenda em emenda | A varredura acima, feita uma vez. Campo novo depois exige dizer por que não estava na tabela **Mecanismo:** `tests/unit/test_efeitos.py::test_o_envelope_tem_exatamente_os_campos_da_varredura`. |
| Nó morto bloquear um disco para sempre | Duas formas de evidência, e cercamento quando nenhuma chega. Teste para as três **Mecanismo:** Mecanismo ainda não existe: `T7`. |
| Relógio lido por dentro do domínio | Nenhum módulo de `vzdr.core.domain` chama `now()` — `saude.py` e a máquina do `ciclo.py` recebem `agora` por parâmetro, e o teste fixa o instante. A lista de módulos é derivada da pasta **Mecanismo:** `tests/unit/test_saude.py::test_nenhum_modulo_do_dominio_le_o_relogio`. |
| `degradada` virar coluna sob pressão de desempenho | O plano já diz que a resposta é *view* ou expressão computada, antes de a pressão existir **Mecanismo:** `tests/unit/test_saude.py::test_degradada_nao_e_coluna_em_migracao_nenhuma` — que não existia: esta linha dizia só "o plano já diz", e o meta-checador a pegou. |
| Resultado atrasado aceito como do ciclo corrente | O id do ciclo está no tipo, não na convenção, e há teste do descarte. `Resultado` sem `ciclo_id` não compila **Mecanismo:** `tests/unit/test_efeitos.py::test_ciclo_id_viaja`, `tests/unit/test_efeitos.py::test_resultado_sem_ciclo_id_nao_existe`; o descarte, `T6`. |
| `degradada` virar campo "por conveniência" ao integrar com o `core-003` | Ela é função e não existe como campo; guardá-la exigiria criar o campo, o que aparece na revisão **Mecanismo:** `tests/unit/test_saude.py::test_degradada_nao_e_campo_em_lugar_nenhum_do_dominio`. |
| A forma do efeito endurecer errada | É o ADR-0015, escrito antes das três implementações existirem **Mecanismo:** `tests/unit/test_efeitos.py::test_o_envelope_tem_exatamente_os_campos_da_varredura` — o ADR escrito cedo é a intenção; o que a mantém é o envelope fechado em teste. |
| Alguém derivar constante do laboratório | A spec tem seção própria dizendo que perfil de parque vira parâmetro com padrão **Mecanismo:** `tests/unit/test_saude.py::test_o_fator_e_parametro_e_muda_a_fronteira`. |

## Decisões que viram ADR

- **[ADR-0015](../../docs/adr/0015-efeito-como-valor.md)** — a máquina pede efeitos, não os
  executa. Escrito nesta fase porque o efeito é contrato entre a máquina, a fila do
  `core-003` e o protocolo do agente, e endurece quando as três existirem.

Não viram ADR: a regra do nó e a telemetria por ciclo já estão decididas nos ADRs 0012 e
0013, e esta spec as consome.
