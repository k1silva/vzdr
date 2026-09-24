#!/bin/bash
# censo-discos.sh — inventário somente-leitura dos discos das VMs deste nó.
#
# NÃO escreve em disco de VM. NÃO cria checkpoint. NÃO cria bitmap.
# NÃO altera estado de nada. Só lê metadados.
#
# Uso:
#   ./censo-discos.sh                 # grava em /var/tmp/censo-<no>-<data>.tsv
#   ./censo-discos.sh /caminho/x.tsv  # grava onde você mandar
#
# Rode em TODOS os nós, no mesmo dia. Guarde os arquivos.
# Repita daqui a 48h e compare com censo-delta.sh.

set -uo pipefail

NODE=$(hostname -s)
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="${1:-/var/tmp/censo-${NODE}-${STAMP}.tsv}"

command -v virsh   >/dev/null || { echo "virsh não encontrado" >&2; exit 1; }
command -v qemu-img>/dev/null || { echo "qemu-img não encontrado" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 não encontrado" >&2; exit 1; }

printf 'data\tno\tdominio\tdispositivo\ttarget\tformato\tvirtual_bytes\talocado_bytes\tcaminho\n' > "$OUT"

DOMS=$(virsh list --name 2>/dev/null | sed '/^$/d')
TOTAL=$(printf '%s\n' "$DOMS" | sed '/^$/d' | wc -l)
echo "nó $NODE — $TOTAL domínios em execução" >&2

i=0
while IFS= read -r dom; do
  [ -z "$dom" ] && continue
  i=$((i+1))
  printf '  [%d/%d] %s\n' "$i" "$TOTAL" "$dom" >&2

  virsh domblklist "$dom" --details 2>/dev/null \
  | awk 'NF>=4 && $1!="Type" && $1 !~ /^-+$/ {print $2"\t"$3"\t"$4}' \
  | while IFS=$'\t' read -r dev tgt src; do
      [ -z "${src:-}" ] && continue
      [ "$src" = "-" ] && continue

      fmt="ERRO"; vsz=0; asz=0
      if info=$(qemu-img info -U --output=json "$src" 2>/dev/null) && [ -n "$info" ]; then
        parsed=$(printf '%s' "$info" | python3 -c '
import sys, json
try:
    x = json.load(sys.stdin)
    print("%s %d %d" % (x.get("format", "?"),
                        int(x.get("virtual-size") or 0),
                        int(x.get("actual-size") or 0)))
except Exception:
    print("?  0 0")
' 2>/dev/null) || parsed=""
        if [ -n "$parsed" ]; then
          fmt=$(printf '%s' "$parsed" | cut -d' ' -f1)
          vsz=$(printf '%s' "$parsed" | cut -d' ' -f2)
          asz=$(printf '%s' "$parsed" | cut -d' ' -f3)
        fi
      fi

      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$STAMP" "$NODE" "$dom" "$dev" "$tgt" "$fmt" "$vsz" "$asz" "$src" >> "$OUT"
    done
done <<< "$DOMS"

echo >&2
echo "== resumo — $NODE ==" >&2

awk -F'\t' 'NR>1 && $4=="disk" {
    a[$6] += $8; n[$6]++; tot += $8; cnt++
}
END {
    printf "discos (device=disk): %d\n", cnt
    printf "alocado total: %.2f TiB\n", tot/1024/1024/1024/1024
    print  "por formato:"
    for (f in a) printf "  %-8s %4d discos  %8.2f GiB\n", f, n[f], a[f]/1024/1024/1024
}' "$OUT" >&2

echo >&2
echo "maiores consumidores:" >&2
awk -F'\t' 'NR>1 && $4=="disk" {s[$3]+=$8} END {for (d in s) printf "  %-22s %8.2f GiB\n", d, s[d]/1024/1024/1024}' "$OUT" \
  | sort -k2 -rn | head -8 >&2

echo >&2
RAW=$(awk -F'\t' 'NR>1 && $4=="disk" && $6=="raw"' "$OUT" | wc -l)
if [ "$RAW" -gt 0 ]; then
  echo "ATENÇÃO: $RAW disco(s) em formato raw — não suportam checkpoint:" >&2
  awk -F'\t' 'NR>1 && $4=="disk" && $6=="raw" {printf "  %-22s %-5s %8.2f GiB\n", $3, $5, $8/1024/1024/1024}' "$OUT" >&2
else
  echo "nenhum disco raw — todos suportam checkpoint" >&2
fi

echo >&2
echo "arquivo: $OUT" >&2
