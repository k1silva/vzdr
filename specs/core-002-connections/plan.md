# core-002 — Plano técnico

**Spec:** ./spec.md

## Abordagem

Três camadas, e a fronteira entre elas é o que permite acrescentar um conector sem tocar
no núcleo:

1. **Registro** (`vzdr.core.connections`): tabelas de conexão e cofre, resolução de
   cliente por capacidade. Não sabe o que é um cluster VHI.
2. **Protocolo do conector** (`vzdr.core.connections.connectors`): a interface que todo
   conector implementa — schema, capacidades, health check, fábrica de cliente.
3. **Conector `vhi`** (`...connectors.vhi`): o primeiro, e o único que fala OpenStack.

O teste de que a fronteira existe é o critério de aceite da spec: **um conector fictício
entra num teste sem tocar no núcleo**. Se para acrescentá-lo for preciso editar a camada 1,
a fronteira está no lugar errado — e é melhor descobrir com o fictício do que com o segundo
conector de verdade.

### O cofre, em concreto

Envelope, como a spec decidiu. Em código:

```python
def guardar(repositorio, segredo: Mapping[str, str]) -> UUID   # devolve a referência
def abrir(repositorio, referencia: UUID) -> Mapping[str, str]  # uso interno, nunca API
def reembrulhar(conexao, kek_nova: bytes) -> int               # rotação de KEK
```

- **DEK** por credencial, 256 bits, aleatória. Cifra o segredo com AES-GCM.
- **KEK** vem de `VZDR_KEK` (base64), sem padrão. Ausente → o processo recusa subir, com
  mensagem dizendo o que falta. É a mesma regra do `criar_papeis_db`: senha padrão que
  funciona é como credencial de laboratório chega em produção.
- A DEK é guardada cifrada pela KEK, ao lado do dado. `reembrulhar` decifra e recifra
  **só as DEKs** — as credenciais não são tocadas, e por isso a rotação é barata o
  bastante para acontecer.
- A KEK tem **identificador** gravado junto de cada DEK. Sem isso, rotação parcial
  interrompida deixa linhas que ninguém sabe com qual chave abrir.

`abrir()` não tem caminho de API: quem a chama é o código que monta o cliente do conector,
dentro do processo. A spec diz que o campo é de escrita, e a forma de garantir isso é não
existir função que devolva segredo para fora.

### Como se prova que a credencial não vaza

Não com revisão. Com um teste que:

1. cadastra uma conexão com um segredo reconhecível;
2. provoca falha de autenticação de verdade contra o conector fictício;
3. captura **log, exceção, *traceback* formatado e as duas tabelas de auditoria**;
4. afirma que o segredo não aparece em nenhum dos quatro.

O passo 3 é o que importa: `repr()` de exceção de biblioteca HTTP costuma carregar o corpo
da requisição, e é assim que um segredo cifrado em repouso aparece em texto puro num
agregador de erro.

### Dependência nova: criptografia

`cryptography` é a única candidata séria para AES-GCM em Python, e a stdlib não tem AEAD.
Justificativa na spec (cofre). Alternativa considerada e descartada: `hashlib`+`hmac` não
fazem cifragem, e implementar AEAD à mão é como se perde chave.

## Módulos tocados

| Pacote | O que muda |
| --- | --- |
| `packages/core-connections` | **Ganha código.** Registro, cofre, protocolo de conector, conector `vhi` |
| `deploy/migrations` | `0007`: `conexao`, `cofre`, `capacidade_observada` |
| `tests/unit` | Cofre, resolução de capacidade, tradução de protocolo com gravações |
| `tests/db` | Isolamento por tenant das conexões, rotação de KEK |
| `tests/integration` | Conector `vhi` contra o laboratório — o que detecta deriva de gravação |

## Modelo de dados

Migração `0007`.

| Tabela | `tenant_id` | Notas |
| --- | --- | --- |
| `conexao` | **sim** | `tipo`, `nome`, `configuracao` jsonb (sem segredo), `estado`, `verificada_em`, `cofre_id` |
| `cofre` | **sim** | `segredo_cifrado`, `dek_cifrada`, `kek_id`, `algoritmo`, `criado_em` |
| `capacidade_observada` | **sim** | `conexao_id`, `capacidade`, `presente`, `versao_vista`, `visto_em` |

Nenhuma exceção nova à lista fechada de `tenant_id`: as três guardam dado de tenant.

`cofre` é tabela separada de `conexao` para que ler uma conexão não traga o segredo junto
por acidente — a consulta que lista conexões nunca toca a tabela do cofre.

`capacidade_observada` é o que torna "capacidade é o fato" verificável: guarda o que foi
observado e quando, e é contra ela que a comparação "sumiu uma capacidade" acontece.

## Interfaces

```python
class Conector(Protocol):
    tipo: str
    def schema(self) -> Mapping[str, Any]: ...
    def capacidades(self) -> frozenset[str]: ...
    def verificar(self, config, segredo) -> Saude: ...
    def cliente(self, config, segredo, capacidade: str) -> Any: ...

@dataclass(frozen=True)
class Saude:
    ok: bool
    erro_cru: str | None          # P8: nunca traduzido
    capacidades: frozenset[str]
    versoes: Mapping[str, str]

def registrar_conector(conector: Conector) -> None
def resolver(repositorio, conexao_id: UUID, capacidade: str) -> Any
```

`resolver` recusa **na resolução**, não no uso, quando a capacidade não existe — é o que a
spec pede, e é a diferença entre falhar cedo e falhar no meio de um seed.

## Gravações de resposta

Ficam em `tests/gravacoes/<conector>/<caso>.json`, e cada arquivo carrega cabeçalho:

```json
{"origem": "lab-dc1", "coletado_em": "2026-09-25", "microversao": "2.89", "resposta": {...}}
```

`make gravar-vhi` regenera contra o laboratório. Gravação sem cabeçalho falha o teste —
gravação anônima é gravação que ninguém sabe se envelheceu.

## Riscos

| Risco | Mitigação |
| --- | --- |
| KEK perdida torna toda credencial ilegível, e não há recuperação | Documentar que perder a KEK é perder as credenciais; o `kek_id` permite conviver com duas durante rotação. Recuperação é recadastrar, e isso precisa estar escrito antes de acontecer |
| Rotação de KEK interrompida no meio | `kek_id` por linha: as duas chaves coexistem, e a rotação é retomável. Sem ele, metade das linhas fica sem dono |
| Gravação envelhece e o teste passa contra ficção | Cabeçalho com data e origem, e a suíte de integração como quem detecta deriva |
| Conector fictício "de teste" vira dependência do núcleo | Ele vive em `tests/`, nunca em `packages/` — e o checador de fronteiras já recusaria o contrário |
| `cryptography` é dependência com extensão C | É a única candidata séria; a alternativa é implementar AEAD à mão, que é pior |

## Decisões que viram ADR

- **ADR-0014 — cofre com envelope e KEK fora do banco.** Alternativa razoável existe
  (cofre externo desde a v1), o custo é real (mais uma dependência de infraestrutura para
  subir o laboratório), e a decisão afeta toda credencial que o produto vier a guardar.
  Merece registro.

Não vira ADR, porque decorre da spec: health check sob demanda no Marco 0, fronteira de teste
entre tradução e integração, capacidade como fato e versão como proxy.
