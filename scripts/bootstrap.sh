#!/usr/bin/env bash
# Prepara o ambiente de desenvolvimento do zero.
set -u

echo "==> conferindo o scaffold"
bash ./scripts/verificar-scaffold.sh || exit 1

echo
echo "==> conferindo ferramentas"
faltando=""
for cmd in python3 git make; do
  command -v "$cmd" >/dev/null 2>&1 || faltando="$faltando $cmd"
done
if [ -n "$faltando" ]; then
  echo "faltando:$faltando"
  echo "instale com:  apt update && apt install -y$faltando python3-venv"
  exit 1
fi
command -v docker >/dev/null 2>&1 || echo "  aviso: docker ausente — 'make db-up' nao vai funcionar (tudo bem por enquanto)"

echo
echo "==> venv e dependencias"
make setup || exit 1

echo
echo "==> .env"
if [ -f .env ]; then
  echo "  .env ja existe, mantido"
else
  cp .env.example .env && echo "  criado .env — preencha antes de seguir"
fi

echo
echo "==> verificacao"
make check || echo "  algo falhou; veja acima"

cat <<'EOF'

Pronto. Proximos passos:

  1. Leia CONTRIBUTING.md e .specify/memory/constitution.md
  2. Instale o Spec Kit:
       uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
       specify init . --ai copilot
  3. Abra specs/core-001-tenancy/spec.md, revise, e rode /speckit.clarify
  4. So depois: /speckit.plan, /speckit.tasks, /speckit.implement

Uma tarefa, um commit, uma revisao sua.
EOF
