# dr-012 — Preparar ambiente de DR

**Status:** rascunho · **Marco:** M4
**Depende de:** core-002 (conexões e conectores), core-003 (motor de trabalho),
core-007 (API — o endpoint de bootstrap da receptora)

> **Por que spec nova, e não extensão da `core-002`.** Os passos 1 e 2 — credenciais e
> descoberta — são exatamente o conector `vhi` da `core-002`, e esta spec os **consome**,
> não os reimplementa. Do passo 5 em diante o vocabulário é todo de DR: modo de
> transporte, floating IP de replicação, receptora, token de bootstrap, orçamento de
> banda, verificação do export por TLS. Pôr uma receptora dentro da `core-002` faria o
> núcleo conhecer uma feature, contra P10 e P11 — "o que significa replicar uma VM" está
> do lado da feature na tabela de `docs/00-visao.md`.
>
> Por isso a `dr-006` deixa de mandar o onboarding inteiro para a `core-002`: o que é da
> `core-002` é a **conexão** com cada cluster; o **par de sites** é desta spec.

> **Marco M4, depois da `core-007`.** O passo 7 precisa do endpoint de bootstrap da
> receptora, que é da `core-007` (pendência registrada em `deploy/cloud-init/README.md`).
> A `dr-006`, em M3, não depende desta spec: ela pressupõe um par de sites pronto, que em
> M3 é preparado à mão, exatamente como o laboratório de 2026-09-23 fez. Esta spec
> automatiza o que lá foi manual.

**Decisões:** [ADR-0011](../../docs/adr/0011-imagem-e-bootstrap-do-receptor.md),
[ADR-0013](../../docs/adr/0013-orcamento-de-banda-e-janelas.md),
[ADR-0010](../../docs/adr/0010-receptor-e-armazenamento-do-espelho.md)

## Por que

Preparar um par de sites para DR, hoje, é a sequência que o laboratório de 2026-09-23
executou à mão: criar projeto, rede, sub-rede, router, floating IP, security group, a VM
receptora, instalar pacote, gerar PKI, subir export, conferir alcance. Doze passos, cada um
com forma própria de errar em silêncio, e nenhum deles interessante.

O operador clica em **"Preparar ambiente de DR"**, responde ao que a API não souber
responder sozinha, revisa o plano e aplica.

## Escopo

**Dentro:** descoberta e provisionamento da infraestrutura de destino para um par de sites —
projeto, rede, floating IP, security group, receptora, bootstrap — e o registro do par no
catálogo com modo de transporte e orçamento de banda.

**Fora:** proteger VM (`dr-006`), failover, test-failover, failback.

## As cinco regras que decidem se presta

**R1 — Descobrir antes de perguntar.** O wizard não pergunta "você já tem projeto?". Ele
lista, mostra o que encontrou e pergunta só para confirmar ou escolher. Toda pergunta que a
API responde sozinha é uma oportunidade a mais de o operador errar.

**R2 — Plano antes de aplicar.** O passo final mostra exatamente o que será criado — nomes,
tamanhos, IPs, projeto, regras — e nada é criado antes do "aplicar". É o que torna seguro
entregar na mão do administrador do cliente.

**R3 — Idempotente e retomável.** Falhou no passo 6, roda de novo e retoma. Nunca duplica.
Nome determinístico derivado de `(tenant_id, site_id, recurso)`; antes de criar, procura;
se existe e confere, adota; se existe e diverge, para e reporta.

**R4 — O que cria, sabe desfazer.** Todo recurso criado é registrado **antes** de ser
criado, com dono e origem. "Desfazer preparação" existe e é confiável. Onboarding que falha
pela metade não pode deixar lixo no cluster do cliente.

**R5 — Degradar com elegância quando faltar permissão.** Criar projeto no Keystone é
operação de `admin` de nuvem, não de usuário de projeto — e muito cliente não vai conceder
isso. O wizard detecta a falta de permissão, **explica em linguagem de operador** e pede um
projeto existente. Mesma coisa para rede, router e floating IP. Falhar com
`403 Forbidden` cru é inaceitável.

## Duas nuvens, uma máquina de estados

O wizard opera contra **origem e destino**, com credenciais distintas. Falha parcial — um
lado pronto, outro não — é o caso normal, não a exceção. O estado do par de sites precisa
representar isso, e a retomada precisa saber qual lado refazer.

## Passos

1. **Credenciais** dos dois clusters. Valida conectando e lendo, nunca escrevendo.
2. **Descoberta** — projetos, redes, imagens, flavors, quotas, dos dois lados.
3. **Projeto de destino** — escolher existente ou criar (R5).
4. **Rede de destino** — rede, sub-rede, router, escolher ou criar.
5. **Caminho de replicação** — detecta o modo de transporte ([ADR-0008](../../docs/adr/0008-modos-de-transporte.md)):
   confere se a origem alcança a internet, aloca floating IP no destino, propõe a regra de
   security group com o `/32` de saída da origem.
6. **Capacidade e janelas** — capacidade declarada do enlace e o orçamento por janela
   (ADR-0013), no fuso do cliente.
7. **Receptora** — confere a imagem Ubuntu cloud no Glance do destino, escolhe flavor, gera
   o token de bootstrap, renderiza o `user-data` ([ADR-0011](../../docs/adr/0011-imagem-e-bootstrap-do-receptor.md)).
8. **Plano** — tudo que será criado, em tela, antes de qualquer escrita (R2).
9. **Aplicar** — com progresso por recurso e retomada (R3).
10. **Verificar** — a receptora completou o bootstrap, o túnel de saída subiu, e um
    `qemu-img info` contra o export do destino fecha o TLS mútuo. Só então o par de sites
    fica `pronto`.

O passo 10 não é enfeite: foi exatamente a sequência que provou o laboratório, e é a única
coisa que distingue "criei os recursos" de "funciona".

## Critérios de aceite

1. Par de sites completo, do zero, sem nenhum comando manual.
2. Interromper no meio e retomar conclui sem recurso duplicado nem órfão.
3. Rodar duas vezes sobre um par já pronto não cria nada e não altera nada.
4. Sem permissão para criar projeto, o wizard explica e oferece escolher um existente —
   não mostra erro de API.
5. "Desfazer preparação" remove exatamente o que foi criado, e nada além.
6. Ao final, a verificação do passo 10 passa; se não passar, o par não fica `pronto`.
7. Nenhuma chave privada aparece no `user-data` da receptora.
8. Operador de um tenant não enxerga nem alcança par de sites de outro.

## Em aberto

- Onde o wizard roda: control plane com as duas credenciais, ou assistido pelo operador com
  credenciais dele na sessão. Muda o modelo de confiança e precisa de `/speckit.clarify`.
- Se o "desfazer" remove a receptora e os volumes espelho, ou só a infraestrutura de rede.
  Remover volume com espelho dentro é destrutivo e cai em P6.
