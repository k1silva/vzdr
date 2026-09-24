#!/bin/bash
# censo-delta.sh — compara duas passadas do censo e estima crescimento diário.
#
# Uso:
#   ./censo-delta.sh antigo.tsv novo.tsv
#
# Com vários nós, concatene antes:
#   cat censo-*-20260923-*.tsv | grep -v '^data' > passada1.tsv
#   cat censo-*-20260925-*.tsv | grep -v '^data' > passada2.tsv
#   ./censo-delta.sh passada1.tsv passada2.tsv
#
# O que este número é: PISO de crescimento. Sobrescrita não muda o alocado,
# então a taxa real de mudança é maior. Serve para dimensionar armazenamento
# no destino, NÃO para dimensionar banda.

set -uo pipefail
[ $# -eq 2 ] || { echo "uso: $0 antigo.tsv novo.tsv" >&2; exit 1; }

python3 - "$1" "$2" <<'PY'
import sys, csv, datetime

COLS = ["data","no","dominio","dispositivo","target","formato",
        "virtual_bytes","alocado_bytes","caminho"]

def ler(p):
    linhas, datas = {}, []
    with open(p, newline="") as f:
        for r in csv.reader(f, delimiter="\t"):
            if not r or r[0] == "data" or len(r) < 8:
                continue
            d = dict(zip(COLS, r))
            if d["dispositivo"] != "disk":
                continue
            try:
                d["alocado_bytes"] = int(d["alocado_bytes"])
            except ValueError:
                continue
            linhas[(d["dominio"], d["target"])] = d
            datas.append(d["data"])
    return linhas, datas

a, da = ler(sys.argv[1])
b, db = ler(sys.argv[2])
if not a or not b:
    sys.exit("um dos arquivos não tem linhas de disco válidas")

def quando(ds):
    for s in sorted(ds):
        try:
            return datetime.datetime.strptime(s, "%Y%m%d-%H%M%S")
        except ValueError:
            pass
    return None

t0, t1 = quando(da), quando(db)
horas = (t1 - t0).total_seconds() / 3600 if t0 and t1 else 0
GiB = 1024 ** 3

comuns = sorted(set(a) & set(b))
so_a, so_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))

delta_total = sum(b[k]["alocado_bytes"] - a[k]["alocado_bytes"] for k in comuns)
base_total  = sum(b[k]["alocado_bytes"] for k in b)

print("janela: %.1f h  (%s  ->  %s)" % (horas, t0, t1) if horas else "janela: indeterminada")
print("discos comparados: %d" % len(comuns))
if so_a: print("sumiram do segundo censo: %d" % len(so_a))
if so_b: print("apareceram no segundo censo: %d" % len(so_b))
print()
print("alocado total agora : %8.2f GiB  (%.2f TiB)" % (base_total/GiB, base_total/GiB/1024))
print("crescimento na janela: %8.2f GiB" % (delta_total/GiB))
if horas > 0:
    por_dia = delta_total / horas * 24
    print("PISO de crescimento : %8.2f GiB/dia" % (por_dia/GiB))
    if base_total:
        print("                      %.3f%% do parque por dia" % (por_dia/base_total*100))
print()

por_vm = {}
for k in comuns:
    dom = k[0]
    por_vm[dom] = por_vm.get(dom, 0) + b[k]["alocado_bytes"] - a[k]["alocado_bytes"]

moveu = sorted(((v, d) for d, v in por_vm.items() if v != 0), reverse=True)
if moveu:
    print("quem mais cresceu:")
    for v, d in moveu[:10]:
        linha = "  %-22s %+9.2f GiB" % (d, v/GiB)
        if horas > 0:
            linha += "   (%+.2f GiB/dia)" % (v/horas*24/GiB)
        print(linha)
else:
    print("nenhum disco mudou de tamanho alocado na janela")

print()
print("Lembrete: isto é PISO. Sobrescrita não aparece aqui.")
print("Para taxa real de mudança (dimensionar banda) é preciso bitmap.")
PY
