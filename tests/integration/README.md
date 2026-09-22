# Testes de integração

Exigem **libvirt 9.5 e QEMU 8.2 reais** — as mesmas versões do VHI. O fork da Virtuozzo
difere do upstream em pontos que já nos morderam (`--quiesce` ausente no checkpoint,
`bitmap-mode` que só aceita `on-success`).

Não mocke libvirt nem QMP aqui. O comportamento que importa está nas bordas.

## Ambiente

Configure `LIBVIRT_TEST_URI` no `.env`. A VM de CI precisa de:

- libvirt 9.5.0 e QEMU 8.2.0
- Uma VM descartável com disco qcow2 `compat=1.1`
- `qemu-img`, `qemu-nbd`, `nbdinfo`

```bash
make test-int
```

## Limpeza

Todo teste que cria checkpoint, bitmap ou export **tem que limpar no teardown**, inclusive
quando falha. Resíduo em VM de laboratório quebra a rodada seguinte.
