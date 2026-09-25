# ADR-0011: Imagem e bootstrap do receptor

**Data:** 2026-09-23
**Status:** aceito

## Contexto

O [ADR-0010](0010-receptor-e-armazenamento-do-espelho.md) define *o que* o receptor roda:
um `qemu-storage-daemon` controlado por QMP. Falta decidir *como ele nasce*.

No laboratório o receptor foi montado à mão: criar VM, instalar `qemu-utils`, gerar PKI,
subir o export. Nenhum desses passos pode existir no produto, porque cada receptora nova é
um cliente novo ou um pool que encheu.

Duas perguntas: de onde vem o sistema, e como as credenciais chegam nele.

## Decisão

### O sistema vem de imagem padrão, configurado por cloud-init

Na v1 **não existe imagem própria**. A receptora nasce de uma **imagem Ubuntu cloud padrão**
— a que o cluster de destino já tem no Glance — e todo o resto vem do `user-data` do
cloud-init: instalar `qemu-utils`, escrever a configuração, subir a unit do
`qemu-storage-daemon`.

O motivo é remover uma dependência inteira: sem imagem própria não há build, não há
distribuição, não há URL para manter no ar, e não há nada para o cliente aprovar antes de
subir. O custo é tempo de boot maior, que é irrelevante para uma máquina que sobe uma vez
por pool.

**Imagem pré-cozida entra na v2 como otimização**, e aí com regras: construída em CI,
checksum SHA-256 publicado, e a control plane **verifica o checksum antes** de subir para o
Glance do destino. Uma imagem baixada de URL sem verificação é vetor de supply chain, e o
receptor tem escrita em todos os espelhos daquela receptora — comprometer a imagem é
comprometer os espelhos de todos os clientes que a usarem.

### Credencial nunca vem da imagem, e nunca vem inteira no `user-data`

O `user-data` do cloud-init é **legível pela API do Nova** por quem tiver leitura naquele
projeto. Chave privada ali dentro vaza para esse conjunto de pessoas.

Então o `user-data` carrega apenas um **token de bootstrap de uso único**, com validade
curta (minutos, não horas), ligado a `(tenant_id, site_id, receptora)`. A receptora sobe,
apresenta o token à control plane sobre TLS, recebe suas credenciais reais — certificado
de servidor NBD, chave SSH restrita do relé, configuração — e o token é queimado no mesmo
instante. Quem ler o `user-data` depois disso encontra um token morto.

Regras que decorrem:

1. O token é de uso único e a queima é registrada. Segunda apresentação é recusada **e
   alarmada** — significa que alguém leu o `user-data` ou que a receptora foi clonada.
2. Token expirado não é renovado em silêncio. A control plane destrói a receptora e
   provisiona outra, porque uma receptora que não completou o bootstrap não tem estado a
   preservar.
3. A imagem é genérica e não contém segredo nenhum. Duas receptoras de clientes diferentes
   nascem bit a bit iguais.
4. A CA do par de sites vive na control plane. A receptora recebe certificado emitido, não
   a chave da CA.

### O registro da receptora é o próprio túnel de saída

A receptora não é "descoberta". Ela se registra discando para fora: com a chave recebida no
bootstrap, abre o túnel de saída para o relé na porta que a control plane atribuiu
([ADR-0009](0009-separacao-rele-control-plane.md)). A porta abrir é o sinal de que a
receptora está viva; a porta cair é o sinal de que não está.

Isso dispensa health-check de entrada, dispensa porta de escuta na receptora além do que o
modo de transporte exige, e reaproveita o canal de controle que já existe.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Imagem própria já na v1, baixada de URL pública | Descartada por ordem, não por mérito: adianta o tempo de boot mas antecipa build, assinatura, hospedagem e verificação — trabalho que só se paga quando houver volume de receptoras |
| Chave privada direto no `user-data` | Legível pela API do Nova, sem expiração, e a mesma chave continua válida para sempre depois de lida |
| Receptora configurada por SSH pela control plane depois do boot | Exige que a control plane alcance a receptora de fora, que é exatamente o que o ADR-0008 evita, e inverte o sentido de discagem que o resto do sistema usa |
| Descoberta ativa por varredura ou health-check de entrada | O túnel de saída já é o sinal de vida, e é mais barato e mais seguro que qualquer varredura |

## Consequências

- O `user-data` vira artefato gerado por tenant e por receptora, com segredo de curta
  duração. Precisa ser tratado como tal nos logs: nunca impresso inteiro.
- A control plane ganha um endpoint de bootstrap, que é a única superfície que aceita token
  em vez de certificado. Merece limite de taxa e alarme próprio.
- Boot mais lento na v1 (`apt install` a cada receptora nova). Aceitável; medir e revisitar
  quando o pool crescer.
- Dependência da imagem Ubuntu cloud existir no Glance do destino. O onboarding de site
  verifica isso e falha cedo, com mensagem clara, em vez de falhar no provisionamento.
- Versão do `qemu-utils` passa a variar com o que o repositório do cliente serve. O
  onboarding registra a versão encontrada; a suíte de compatibilidade roda contra ela.

### O que a suíte de compatibilidade confere

A lista mora aqui, e não espalhada, porque foi este ADR que criou a obrigação. Cada linha
existe porque alguma decisão depende do resultado — suíte que confere o que ninguém usa é
tempo de boot gasto à toa.

| O que | Por que depende da versão | Quem depende |
| --- | --- | --- |
| `block-export-del` aceita `mode: hard` | Desconectar cliente ativo é o que mata o escritor zumbi. Sem isso, o cercamento vira reinício do `qemu-storage-daemon` daquela receptora — mais grosseiro, e derruba os exports dos outros discos junto | Cercamento da [`dr-001`](../../specs/dr-001-dominio-ciclo/spec.md), mecânica na [`dr-006`](../../specs/dr-006-provisionamento/spec.md) |
| Comprimento máximo do `node-name` do `blockdev-add` | A lembrança de duas pessoas aqui é **31 caracteres**, e nenhuma das duas verificou. Se o limite existir, o **R3** da `dr-006` estoura com folga: `(tenant_id, vm_id, disco)` são três UUIDs. Aí o nome do nó precisa de forma própria, e forma de nome é identidade — logo domínio | `blockdev-add` da `dr-006` |

Os nomes derivados de ciclo da `dr-001` têm 41 caracteres e **não** são `node-name`:
bitmap, checkpoint e export NBD aceitam nome longo. A linha acima é sobre o nó, que é
outra coisa e é durável.
