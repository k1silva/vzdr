# M5 — por onde o estado do bitmap é legível na VHI — 2026-10-02

> **Feita no cluster VHI de produção**, por um humano, com leitura e **um checkpoint
> reversível, já removido**. Uma VM. O que segue é o que foi lido, e o que vale além daquela
> VM está dito como pergunta, e não como fato.

Medição `M5` do [ADR-0012](../adr/0012-resposta-a-perda-de-bitmap.md), exigida pelo
[ADR-0016](../adr/0016-confianca-no-bitmap.md) antes de o contrato do inventário ser
desenhado (`dr-001/T9`).

## Versões

libvirt 9.5.0, QEMU 8.2.0 (`virsh version`, linha *Running hypervisor*).

## O caminho de leitura existe

- `virsh qemu-monitor-command` funciona num nó gerenciado pela Nova e devolve o
  `query-block` completo.
- `checkpoint-list` e `checkpoint-create-as` funcionam: o checkpoint do libvirt existe neste
  fork.
- **Exige conexão de leitura e escrita com o libvirtd**, mesmo para `query-*`. Conferido no
  código do libvirt 9.5.0 (`src/libvirt-qemu.c`): `virDomainQemuMonitorCommand` faz
  `virCheckReadOnlyGoto(conn->flags, error)` antes de qualquer coisa. A medição foi feita
  como root. Peso de segurança e decisão de implantação: candidata `C-007`.
- O mesmo docstring do libvirt: "A @cmd that queries state without making any modifications
  is safe; A @cmd that alters state that is also tracked by libvirt is unsafe". **Ler pelo
  monitor, escrever pelo libvirt** — registrado no `RemoverCheckpointsAnteriores`.

## O que o `query-block` devolve

Em `inserted.dirty-bitmaps[]`, no nó de formato qcow2:

```json
{ "name": "vzdr-m5-1", "recording": true, "persistent": true,
  "busy": false, "granularity": 65536, "count": 0 }
```

| Fato | O que governa |
| --- | --- |
| `inconsistent` **não apareceu** | É opcional na referência QMP desde o QEMU 4.0 — "true if this is a persistent bitmap that was improperly stored" —, e booleano opcional só é impresso quando verdadeiro. Ausente quer dizer consistente **no QEMU**. No nosso envelope ele é obrigatório: a normalização é do agente, na borda |
| "Implies persistent to be true; recording and busy to be false" | Inconsistente é sempre `recording: false`, então a condição 3 do ADR-0016 já alcança todo inconsistente; `inconsistent` diz o **motivo**. E inconsistente com `recording: true` viola a invariante do próprio QEMU: `FonteIncoerenteError` |
| `granularity: 65536` | Confirma os 2 MiB de bitmap por TiB. O cluster é de 1 MiB com `extended-l2`; o padrão é o cluster limitado a [4 KiB, 64 KiB], então fica em 64 KiB |
| `persistent: true` sem flag nenhuma, com `compat: 1.1` | — |
| `count: 0` funcionando | A entrada do limiar e do ETA (ADR-0016, decisão 4) |
| O cdrom (`ro: true`) não recebeu bitmap | O libvirt não põe bitmap em disco somente-leitura. O ciclo recebe só os graváveis, e a máquina confere a lista contra o `somente_leitura` do inventário. O censo já excluía os 24 discos raw; agora se sabe que não é convenção nossa |
| `node-name` é `libvirt-N-format`, e o N não segue os targets (`vda` era `libvirt-1`, o cdrom `sda`, `libvirt-2`) | Atribuído por partida do domínio: nunca guardar, ler no momento de agir, e casar pelo `filename` com o caminho do volume |
| O libvirt nomeia o bitmap exatamente como o checkpoint, o mesmo em todos os discos | Confirma por medição que só o export pode levar o disco no nome (`identidade.py`) |
| Volume de dados com `backing_file_depth: 0` | As condições 1 e 2 do ADR-0016 ficam triviais **para esta VM**. Para o parque, é pergunta do censo |

## A armadilha

O `dirty-flag` do qcow2 **não é** dirty bitmap. É o bit de sujo da imagem, par do
`lazy-refcounts`, e vem verdadeiro em toda VM ligada. Lê-lo como estado do bitmap é o
engano do `dirty-bitmaps: state false`, que já custou um chamado, pela mesma porta.

## O que fica em aberto

- **`query-block-jobs` não foi medido.** O `jobs_em_curso` do inventário depende dele, e a
  forma do retorno está suposta: sob que chave vem o id (`device` ou `id`), e se o fork
  mantém o esquema. Só-leitura, sem efeito nenhum:
  `virsh qemu-monitor-command <dom> --pretty '{"execute":"query-block-jobs"}'`. Não
  bloqueia o contrato; bloqueia a `dr-001/T6` de depender do campo.
- **O caminho do `filename` no `query-block`.** A M5 casou node-name e disco pelo
  `filename`, e o inventário passou a usá-lo como identidade de cada imagem da cadeia
  (`arquivo`). O registro não guarda a saída crua: em que chave ele veio — `inserted.file`
  ou `inserted.image.filename`, e nas imagens de backing `backing-image.filename` — fica
  para conferir junto com o `query-block-jobs`.

- **A M4**, agora conferência, com a previsão registrada antes de rodar, no
  [roadmap](../03-roadmap.md). Precisa de um nó que possa ser drenado.
- **O backup nativo da VHI usa dirty bitmap nas mesmas imagens**, com `compat: 1.1` como
  requisito. `busy` pode vir dele, e não de um zumbi nosso. O desenho trata (repete, escala
  por prazo; nome que não é nosso é órfão), mas a pergunta operacional fica: candidata `C-008`.
