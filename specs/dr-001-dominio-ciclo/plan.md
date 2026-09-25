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
def avancar(estado: EstadoDoCiclo, entrada: Optional[Resultado]) -> Transicao
```

`Optional`, e não `Resultado | None`: `core-domain` é alvo 3.9 pelo
[ADR-0007](../../docs/adr/0007-alvo-de-python-por-pacote.md), e quem garante a sintaxe é o
`ruff`, não o `mypy`. Vale para todo código desta spec.

`Transicao` traz o estado novo e os efeitos a pedir. **Função, não objeto com métodos**: o
estado entra e sai, nada é guardado. É o que torna um teste uma linha e um cenário de falha
uma lista de resultados.

O [ADR-0015](../../docs/adr/0015-efeito-como-valor.md) decide a forma do efeito; este plano
só a executa.

### Serialização é parte do tipo, não um detalhe

Efeito e resultado nascem com `para_json` e `de_json`, e o teste de ida e volta é escrito
junto — não depois, quando a fila do `core-003` existir.

O motivo é o do próprio ADR: se a serialização vier depois, ela vai ser moldada pelo que já
foi escrito, e o primeiro efeito que não couber numa linha vai ganhar uma exceção em vez de
um conserto.

### `degradada` não é estado da máquina

É **conta**, e por isso vive em `saude.py`, não em `ciclo.py`:

```python
def esta_degradada(idade_do_ponto: timedelta, rpo: timedelta, fator: float = 2.0) -> bool
```

Nenhuma transição a produz, nenhum campo a guarda. O `fator` é parâmetro com padrão,
porque depende de perfil de parque — e a spec proíbe constante derivada de parque.

**O relógio entra por parâmetro, nunca lido por dentro.** Quem recebe `idade_do_ponto` já
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

`nome_do_bitmap(ciclo_id)` e `nome_do_checkpoint(ciclo_id)`, puras e determinísticas.
Órfão ganha definição — nome cujo ciclo não está ativo — e a reconciliação compara conjuntos
em vez de casar prefixo.

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
class Fase(Enum):          # onde o ciclo está
    OCIOSO, RECONCILIANDO, CONGELANDO, COPIANDO,
    VERIFICANDO_NO_DESTINO, CONCLUIDO, FALHOU, PRECISA_RESYNC

@dataclass(frozen=True)
class EstadoDoCiclo:
    ciclo_id: UUID
    vm_id: UUID
    fase: Fase
    janelas_pendentes: int
    no_de_origem: str          # ADR-0012: parte do estado, comparado a cada ciclo
    volumes: tuple[VolumeDoCiclo, ...]
    telemetria: Telemetria
```

`no_de_origem` está aqui porque o ADR-0012 o tornou parte do estado do ciclo, não porque o
ciclo precise dele para avançar. Comparar o nó atual com o gravado é a primeira coisa que a
máquina faz.

## Interfaces

```python
# efeitos.py — o que a máquina pede
@dataclass(frozen=True)
class Efeito:
    ciclo_id: UUID             # ADR-0015, propriedade 3
    def para_json(self) -> dict[str, Any]: ...

class EfeitoDeDisco(Efeito):
    # ADR-0015, propriedade 4. Sem chave, dois blockdev-backup do MESMO ciclo
    # podem escrever o mesmo espelho — e o ciclo_id nao distingue.
    def chave_de_exclusao(self) -> ChaveDeExclusao: ...   # no minimo (vm, disco)

class CriarCheckpoint(Efeito): ...
class IniciarCopia(Efeito): ...
class DescartarBitmap(Efeito): ...
class ConfirmarNoDestino(Efeito): ...
class InventariarHypervisor(Efeito): ...   # a reconciliação
class CercarDestino(Efeito): ...           # derruba o export; ver dr-006 para a mecanica

@dataclass(frozen=True)
class Resultado:
    ciclo_id: UUID
    @classmethod
    def de_json(cls, dados: Mapping[str, Any]) -> "Resultado": ...

# ciclo.py — a máquina
def avancar(estado: EstadoDoCiclo, entrada: Optional[Resultado]) -> Transicao
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
pedido, é a fotografia do hypervisor. Fundi-la em `avancar` faria a assinatura aceitar dois
tipos de entrada e a função ramificar no começo.

## Riscos

| Risco | Mitigação |
| --- | --- |
| A invariante da falha cair numa "otimização" | Teste **parametrizado sobre a enumeração de falhas**, afirmando que nenhum caminho produz resync completo. É o teste mais importante do projeto, não só da spec |
| A evidência ser pedida ao detentor do lease | A spec diz explicitamente que a consulta é sobre o hypervisor e roteável por qualquer agente com acesso a ele. É a implementação natural e é a errada |
| Nó morto bloquear um disco para sempre | Duas formas de evidência, e cercamento quando nenhuma chega. Teste para as três |
| Relógio lido por dentro de `saude.py` | Nenhuma função do módulo chama `now()`; a data entra por parâmetro, e o teste fixa o instante |
| `degradada` virar coluna sob pressão de desempenho | O plano já diz que a resposta é *view* ou expressão computada, antes de a pressão existir |
| Resultado atrasado aceito como do ciclo corrente | O id do ciclo está no tipo, não na convenção, e há teste do descarte. `Resultado` sem `ciclo_id` não compila |
| `degradada` virar campo "por conveniência" ao integrar com o `core-003` | Ela é função e não existe como campo; guardá-la exigiria criar o campo, o que aparece na revisão |
| A forma do efeito endurecer errada | É o ADR-0015, escrito antes das três implementações existirem |
| Alguém derivar constante do laboratório | A spec tem seção própria dizendo que perfil de parque vira parâmetro com padrão |

## Decisões que viram ADR

- **[ADR-0015](../../docs/adr/0015-efeito-como-valor.md)** — a máquina pede efeitos, não os
  executa. Escrito nesta fase porque o efeito é contrato entre a máquina, a fila do
  `core-003` e o protocolo do agente, e endurece quando as três existirem.

Não viram ADR: a regra do nó e a telemetria por ciclo já estão decididas nos ADRs 0012 e
0013, e esta spec as consome.
