# Constitution — vzdr

Princípios inegociáveis. Toda spec, todo plano e todo código herdam daqui.
Em caso de conflito com qualquer outro documento, este vence.

## Segurança de dados

**P1. Nunca escrever nos discos de origem.**
O agente lê volumes de VMs de produção. A única escrita permitida na origem é metadado
de dirty bitmap no qcow2. Qualquer outra escrita é bug crítico.

**P2. Nenhum checkpoint é apagado antes da confirmação de gravação no destino.**
Copiar, confirmar, só então limpar. Inverter isso destrói a cadeia silenciosamente.

**P3. Todo congelamento de filesystem tem descongelamento garantido.**
`domfsfreeze` só é emitido com `try/finally` e watchdog independente do processo.
VM de cliente travada por agente que morreu é falha inaceitável.

**P4. Ciclo interrompido nunca corrompe a cadeia.**
Falha significa descartar o bitmap temporário e tentar no próximo ciclo, mergeando uma
janela a mais. Nunca resync silencioso, nunca estado parcial aceito.

**P5. Ponto de recuperação é atômico por VM.**
VM de vários discos só ganha ponto quando todos os volumes completaram o mesmo ciclo.
Snapshot parcial é descartado inteiro.

## Operação

**P6. Toda operação destrutiva exige confirmação explícita e entra na auditoria.**
A confirmação é humana, mesmo quando o pedido veio de um assistente de IA.

**P7. Toda funcionalidade existe em API antes de existir em interface.**
A interface e a CLI são clientes da mesma API. Nada de lógica em controlador de tela.
É isso que permite automação e assistente de IA sem reescrita.

**P8. Erro cru preservado.**
O log guarda a falha original, com o comando e a resposta. Nunca traduzir para mensagem
genérica. Diagnóstico às três da manhã depende disso.

## Plataforma

**P9. `tenant_id` em toda tabela, desde a primeira migração.**
Nasce com um tenant, mas com a fronteira desenhada. Retrofitar é reescrever o núcleo.

**P10. Se duas features precisariam da mesma coisa, ela é do núcleo.**
Conexões, inventário, fila de jobs, auditoria, segredos: núcleo.
Lógica de dirty bitmap: feature.

**P11. Features não conhecem umas às outras.**
Não importam nem leem tabelas umas das outras. Conversam por eventos, via o núcleo.
O núcleo nunca importa de uma feature.

**P12. O núcleo cresce quando uma feature precisa dele, não antes.**
Não construir plataforma antes de produto. A abstração se prova com uso real.

**P13. Todo sistema externo entra como conexão tipada.**
Cluster VHI, monitoramento, billing, object storage — todos são conectores registrados
no núcleo, com schema de configuração, credenciais no cofre e health check. Nenhuma
feature abre conexão própria com sistema externo por fora do registro.
