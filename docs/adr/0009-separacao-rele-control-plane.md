# ADR-0009: Separação entre relé e control plane

**Data:** 2026-09-23
**Status:** aceito

## Contexto

Os modos `jump-ssh` e `rendezvous-wg` do [ADR-0008](0008-modos-de-transporte.md) exigem um
relé: uma máquina com IP público onde os agentes dos clientes terminam túneis de saída. A
tentação é hospedá-lo na mesma VM da control plane, que já existe.

A control plane guarda as credenciais OpenStack dos **dois clusters de cada cliente** e o
banco multi-tenant protegido por RLS ([ADR-0006](0006-isolamento-por-rls.md)). O relé é a
única superfície exposta à internet.

## O que este relé é, e o que não é

O **[ADR-0002](0002-espelho-como-volume-cinder.md)** descartou "relay por aplicação externa — destrói o RTO e dobra a banda".
Este relé é outra coisa, e a distinção é a razão de ele ser aceitável:

| | Relé descartado no ADR-0002 | Relé deste ADR |
|---|---|---|
| Camada | aplicação: termina o protocolo | transporte: encaminha bytes |
| Vê o dado | sim, reprocessa e reencoda | não, é ciphertext TLS fim a fim |
| Caminho do failover | está dentro dele | **fora** — o espelho já está no DC-2 |
| Efeito no RTO | direto | nenhum |

O relé nunca participa da recuperação. Quando o desastre acontece, o espelho e os pontos
de recuperação já estão no destino; o relé podia estar desligado há uma hora e o failover
acontece igual. Ele é caminho de replicação, não de recuperação.

O custo de banda dobrado é real, mas no relé, não no caminho fim a fim — e só nos modos em
que ele é usado, que são a exceção e não o padrão.

## Decisão

Relé e control plane são **componentes separados, colocalizáveis**. No laboratório rodam na
mesma VM; em produção, em VMs distintas. A separação é decisão de deploy, e o código nunca
assume colocalização.

Três regras garantem que a separação custe um `systemctl` e não um refactor:

1. **O relé não importa código do `vzdr`.** É `sshd` configurado, mais nada. A interface
   entre os dois é "uma porta TCP em localhost que fala NBD". Se a control plane precisar
   *perguntar* algo ao relé, o desenho quebrou.
2. **O relé é burro e sem estado.** Quem sabe qual porta pertence a qual site é a control
   plane, porque foi ela que atribuiu; está no banco dela. O relé não guarda mapa, não lê
   arquivo de estado, não conhece o conceito de tenant.
3. **Credencial de cluster não entra no ambiente do relé.** Mesmo na mesma VM: usuário
   próprio, unit systemd própria, `EnvironmentFile` 0600 do usuário `vzdr`.

**Isolamento entre tenants é imposto pelo `sshd`, não por convenção.** Uma chave por site
protegido, com a restrição na própria chave:

```
permitlisten="127.0.0.1:49301",no-pty,no-agent-forwarding,no-X11-forwarding,command="/bin/false" ssh-ed25519 AAAA... site-cliente-a-dc1
permitlisten="127.0.0.1:49302",no-pty,no-agent-forwarding,no-X11-forwarding,command="/bin/false" ssh-ed25519 AAAA... site-cliente-b-dc1
```

O site A não consegue ligar na porta do site B — o `sshd` recusa. `permitlisten` do OpenSSH
não aceita faixa, só porta fixa ou `*`, então a porta é **fixa por site**, atribuída pela
control plane e gravada junto do `tenant_id`. Isso também dá rastreabilidade: a porta 49301
é sempre aquele site, em log, em `ss`, em tudo.

Quando separados, a control plane alcança as portas encaminhadas discando `ssh -L` para o
relé. O relé nunca escuta em interface pública além da 22.

## Alternativas consideradas

| Alternativa | Por que não |
| --- | --- |
| Tudo numa VM, permanentemente | Defensável só para appliance single-tenant on-premise, que não é o modelo. Uma CVE de `sshd` ou um `PermitListen` mal escrito entregaria todos os tenants de uma vez, e não adianta RLS no Postgres se o processo que atende a internet roda na mesma máquina que o banco |
| Um usuário SSH para todos os sites | Sem `permitlisten` por chave, o isolamento entre tenants vira convenção — e convenção não é controle |
| Relé com lógica (autenticar, rotear, contabilizar) | Qualquer estado no relé impede substituí-lo e o transforma em alvo de valor. É também o que o tornaria o relé que o ADR-0002 descartou |

## Consequências

- O relé escala horizontalmente porque é sem estado: vários relés, um por região, sem
  migrar nada. Isso importa porque seu eixo de escala (banda) é diferente do da control
  plane (CPU e banco).
- Um seed grande satura CPU de cripto e rede do relé. Colocalizado, isso degrada a API e os
  health checks **durante a replicação** — exatamente quando a control plane precisa estar
  responsiva, e muitas vezes com o cliente olhando.
- O onboarding de site passa a incluir: gerar par de chaves, registrar a chave restrita no
  relé, atribuir porta, gravar `(tenant_id, site_id, porta, fingerprint)`.
- Portas são recurso finito e atribuído. Precisam de liberação no offboarding, senão vazam.
