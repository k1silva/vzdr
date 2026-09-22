#!/usr/bin/env bash
# Censo de formatos de volume num hypervisor VHI.
# Volumes raw nao suportam dirty bitmap, entao nao podem ser replicados
# incrementalmente. Rode em TODOS os nos e some.
set -euo pipefail

for d in $(virsh list --name); do
  virsh domblklist "$d" --details | awk -v D="$d" '$2=="disk"{print D, $3, $4}'
done | while read -r dom alvo arquivo; do
  info=$(qemu-img info -U --output=json "$arquivo" 2>/dev/null \
    | python3 -c 'import sys,json;x=json.load(sys.stdin);print(x.get("format"), round(x.get("virtual-size",0)/2**30,1), round(x.get("actual-size",0)/2**30,2))' 2>/dev/null)
  echo "$dom $alvo ${info:-ERRO}"
done | column -t
