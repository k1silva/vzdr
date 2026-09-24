# Receptor — imagem e cloud-init

Decisão em [ADR-0011](../../docs/adr/0011-imagem-e-bootstrap-do-receptor.md).

A receptora nasce de uma **imagem Ubuntu cloud padrão**, a que o cluster de destino já tem
no Glance. Não há imagem própria na v1: sem build, sem distribuição, sem URL para manter no
ar, sem nada para o cliente aprovar. Todo o resto vem do `user-data` em
[`receptor.yaml`](receptor.yaml).

## Campos substituídos

A control plane renderiza o template por receptora:

| Campo | Origem |
|---|---|
| `{{ control_plane_url }}` | configuração global |
| `{{ bootstrap_token }}` | gerado na hora, uso único, vida curta |
| `{{ tenant_id }}` | tenant dono do site |
| `{{ site_id }}` | par de sites |
| `{{ receptor_id }}` | identidade da receptora no pool |

## O que nunca entra aqui

`user-data` é legível pela API do Nova por quem tiver leitura no projeto. Então:

- **nenhuma chave privada** — nem do NBD, nem do SSH do relé;
- **nenhum certificado**;
- **nenhuma senha**.

Só o token de bootstrap. Ele vale uma vez e por poucos minutos. Quem ler o `user-data`
depois do boot encontra um token morto.

## Sequência de boot

```
cloud-init instala pacotes
  → vzdr-bootstrap.service
      POST token → control plane
      recebe PKI do NBD + chave SSH do relé + config
      grava com permissão restrita
      queima o token local
      habilita as duas units abaixo
  → vzdr-receptor.service   (qemu-storage-daemon, sem export nenhum)
  → vzdr-tunel.service      (ssh -R para o relé)
```

O receptor sobe **sem export algum**. Os exports entram e saem em tempo de execução por
QMP, conforme a control plane provisiona discos ([ADR-0010](../../docs/adr/0010-receptor-e-armazenamento-do-espelho.md)).

O túnel de saída é o registro: **a porta abrir é o sinal de que a receptora está viva, a
porta cair é o sinal de que não está.** Não há health-check de entrada, não há varredura.

## Regras de segurança do bootstrap

1. Token é de uso único e a queima é registrada. Segunda apresentação é recusada **e
   alarmada** — significa `user-data` lido por terceiro ou receptora clonada.
2. Token expirado não é renovado em silêncio: a control plane destrói a receptora e
   provisiona outra. Receptora que não completou o bootstrap não tem estado a preservar.
3. A CA do par de sites vive na control plane. A receptora recebe certificado emitido,
   nunca a chave da CA.
4. A imagem é genérica. Duas receptoras de clientes diferentes nascem bit a bit iguais.

## Pendências antes de usar em cliente

- [ ] **Validar a sintaxe do `--nbd-server` com TLS** contra a versão de
      `qemu-storage-daemon` do pacote `qemu-utils` do destino. A forma usada aqui
      (`tls-creds=` e `tls-authz=` na mesma opção) segue os argumentos de
      `nbd-server-start`, mas não foi executada — o laboratório de 2026-09-23 usou
      `qemu-nbd`, não o daemon.
- [ ] **Endpoint `/v1/receptores/bootstrap`** ainda não existe na control plane.
- [ ] **Verificar que a imagem Ubuntu cloud existe no Glance do destino** — o onboarding de
      site deve falhar cedo, com mensagem clara, em vez de falhar no provisionamento.
- [ ] **Registrar a versão de `qemu-utils`** encontrada no destino: ela varia com o
      repositório do cliente, e a suíte de compatibilidade roda contra ela.

## v2 — imagem pré-cozida

Otimização de tempo de boot, não requisito. Quando entrar: construída em CI, checksum
SHA-256 publicado, e a control plane **verifica o checksum antes** de subir para o Glance do
destino. Imagem baixada sem verificação é vetor de supply chain, e o receptor tem escrita em
todos os espelhos daquela receptora.
