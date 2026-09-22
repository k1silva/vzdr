#!/usr/bin/env bash
# Mede a taxa de mudanca de uma VM sem transferir um unico byte.
# Cria um checkpoint e le o contador do bitmap ao longo do tempo.
#
#   ./medir-taxa-mudanca.sh instance-0000028e 300
#
set -euo pipefail

DOM="${1:?uso: $0 <dominio> [intervalo_segundos]}"
INTERVALO="${2:-300}"
PROBE="dr-measure"

if ! virsh checkpoint-list "$DOM" --name 2>/dev/null | grep -qx "$PROBE"; then
  virsh checkpoint-create-as "$DOM" --name "$PROBE" --diskspec vda,checkpoint=bitmap
  echo "bitmap de medicao criado em $DOM"
fi

anterior=""
anterior_t=""
while true; do
  agora=$(date +%s)
  atual=$(virsh qemu-monitor-command "$DOM" '{"execute":"query-block"}' | python3 -c "
import sys, json
for x in json.load(sys.stdin)['return']:
    for b in (x.get('inserted') or {}).get('dirty-bitmaps', []):
        if b['name'] == '$PROBE':
            print(b['count']); raise SystemExit
print(0)")

  linha=$(printf '%s  sujo=%9.3f GiB' "$(date '+%H:%M:%S')" "$(echo "$atual/1073741824" | bc -l)")
  if [ -n "$anterior" ]; then
    taxa=$(echo "($atual - $anterior) / ($agora - $anterior_t)" | bc -l)
    linha="$linha   $(printf 'taxa=%7.2f MiB/s   projecao=%.1f GiB/dia' \
      "$(echo "$taxa/1048576" | bc -l)" "$(echo "$taxa*86400/1073741824" | bc -l)")"
  fi
  echo "$linha"

  anterior=$atual
  anterior_t=$agora
  sleep "$INTERVALO"
done
