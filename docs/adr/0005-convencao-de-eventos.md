# ADR-0005: Nome de evento é `dominio.acao`, no passado, em snake_case

**Data:** 2026-09-22
**Status:** aceito

## Contexto

`core-001` precisou nomear dois eventos de auditoria e não havia convenção. `core-002` já
fala em "evento emitido" sem dizer como ele se chama. `core-006` vai transformar isso num
barramento com assinatura externa por webhook.

O ponto que força a decisão agora não é estética: nome de evento vira contrato público. Um
assinante de webhook vive **fora deste repositório** — no Zabbix de alguém, num runbook, num
filtro de alerta. Renomear um evento depois quebra esse assinante em silêncio, sem que
nenhum teste nosso perceba, e sem que exista um lugar onde consertar. Renomear símbolo de
código é `make check` e um commit; renomear evento publicado é uma migração combinada com
terceiros.

Fixar a convenção antes do primeiro evento existir custa esta página. Fixar depois custa
janela de depreciação.

## Decisão

Todo evento se chama `dominio.acao`:

- **`dominio`** é o módulo dono, em snake_case: `tenancy`, `conexoes`, `dr`.
- **`acao`** é o que aconteceu, no **passado**, em snake_case.

```
tenancy.papel_concedido
tenancy.papel_autoconcedido
dr.ciclo_concluido
connections.verificacao_falhou
```

### A forma é mista de propósito

`connections.verificacao_falhou` **está certo**, e parece errado dos dois lados. Vale
escrever por quê, porque quem chegar depois vai querer "normalizar":

| Parte | Idioma | De onde vem |
| --- | --- | --- |
| `connections` | inglês | é o nome do **módulo** dono, e módulo é infraestrutura |
| `verificacao_falhou` | português | é termo de negócio |

É exatamente a regra do `AGENTS.md` — termo de negócio em português, o resto em inglês —
aplicada a um nome que atravessa a fronteira. Normalizar para `conexoes.*` desalinha do
módulo e quebra o checador, que deriva o domínio de `packages/*/src/**/py.typed`.
Normalizar para `connections.verification_failed` traduz termo de negócio, que é o que a
convenção recusa.

Este exemplo dizia `conexoes` e **contradizia a própria decisão acima**. Passou
despercebido porque, até o `check_eventos.py` existir, nada derivava nada deste documento:
ele não casou com módulo nenhum e o erro apareceu.

O prefixo é por módulo porque é por ele que `core-006` roteia e filtra — um assinante que
quer tudo de DR assina `dr.*` sem enumerar evento por evento.

O passado é porque evento descreve o que aconteceu, não o que se pede. `ciclo_concluido` é
fato consumado; `concluir_ciclo` seria comando. Misturar os dois num barramento faz o
assinante não saber se pode reagir ou se ainda dá tempo de interferir.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Nome plano (`papel_concedido`) | Sem prefixo, `core-006` não tem por onde rotear, e dois módulos colidem no dia em que ambos tiverem `criado` |
| Verbo no imperativo (`dr.concluir_ciclo`) | Confunde evento com comando; assinante não sabe se o fato já é irreversível |
| `PascalCase` estilo classe (`dr.CicloConcluido`) | Evento atravessa JSON, URL de filtro e configuração de terceiro, onde maiúscula vira fonte de erro |
| Decidir quando `core-006` chegar | O primeiro evento nasce em `core-001`, quatro specs antes; renomear depois já seria quebra de contrato |

## Consequências

Fica mais fácil: rotear e filtrar por módulo, assinar `dr.*`, e ler o log sabendo que tudo
ali é fato consumado. O nome do evento diz o dono, o que ajuda quando uma feature reage ao
que outra fez sem conhecê-la (P11).

Fica mais difícil: mudar um evento de módulo passa a ser mudança de contrato, não
refatoração — mover algo de `dr` para o núcleo renomeia o evento para quem assina. E a
convenção precisava de um checador na CI para não erodir.

**Ele existe:** `tests/invariants/check_eventos.py`, desde a TI3 da `core-001`. Ele confere
que evento declarado e evento emitido são o mesmo conjunto, nos dois sentidos, que cada um
tem teste, e que a ação é particípio e não imperativo. Esta linha dizia que a convenção
dependia de revisão humana, e ficou assim depois que ela deixou de depender — o tipo de
afirmação velha que faz alguém confiar menos do que deveria.
