#!/usr/bin/env bash
# Confere se os arquivos ocultos sobreviveram ao unzip.
# Alguns extratores descartam dotfiles, e ai o metodo inteiro fica sem a constitution.
set -u

ESSENCIAIS=(
  "AGENTS.md"
  "CONTRIBUTING.md"
  ".specify/memory/constitution.md"
  ".vscode/settings.json"
  ".github/workflows/ci.yml"
  ".gitignore"
  ".env.example"
  "specs/README.md"
  "tests/invariants/check_core_domain_pure.py"
)

faltando=0
for f in "${ESSENCIAIS[@]}"; do
  if [ -e "$f" ]; then
    printf '  ok      %s\n' "$f"
  else
    printf '  FALTA   %s\n' "$f"
    faltando=1
  fi
done

if [ "$faltando" -ne 0 ]; then
  cat <<'EOF'

Arquivos faltando. Provavelmente o unzip descartou os ocultos.
Extraia de novo com:

    unzip -o vzdr.zip

E confira com "ls -a" — dotfiles nao aparecem no "ls" normal.
EOF
  exit 1
fi

echo
echo "scaffold completo"
