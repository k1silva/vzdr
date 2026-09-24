.PHONY: setup lint fmt typecheck test test-db test-int invariants check db-up db-down clean

VENV := .venv
PIP := $(VENV)/bin/pip
BIN := $(VENV)/bin

# Raizes dos pacotes, derivadas do layout. Nao e uma lista para manter: se um
# pacote novo aparecer em packages/, ele entra sozinho. O mypy precisa disto
# porque `explicit_package_bases` so consegue montar o nome pontilhado de um
# namespace package (PEP 420) a partir da raiz de origem. Sem isso o override
# de `vzdr.core.domain.*` deixa de casar e o --strict do dominio cai calado.
MYPY_SRC := $(shell ls -d packages/*/src 2>/dev/null | tr '\n' ':')

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install ruff mypy pytest pytest-cov
	# driver do Postgres: justificado em specs/core-001-tenancy/plan.md
	$(PIP) install 'psycopg[binary]'
	# Pacotes em modo editavel. E o que faz `import vzdr.*` funcionar no pytest
	# e no mypy sem lista de caminhos no pyproject.toml.
	for p in packages/*/; do $(PIP) install -q -e "$$p" || exit 1; done
	@echo "pronto. ative com: source $(VENV)/bin/activate"

lint:
	$(BIN)/ruff check packages tests scripts
	$(BIN)/ruff format --check packages tests scripts

fmt:
	$(BIN)/ruff format packages tests scripts
	$(BIN)/ruff check --fix packages tests scripts

typecheck:
	MYPYPATH=$(MYPY_SRC) $(BIN)/python scripts/checar_mypy.py packages scripts
	# mypy nao aceita python_version por modulo (e opcao global), entao o que roda no
	# hypervisor passa por uma segunda invocacao. 3.10 e o piso que o mypy aceita —
	# quem garante a sintaxe de 3.9 e o ruff. Ver ADR-0007.
	MYPYPATH=$(MYPY_SRC) $(BIN)/python scripts/checar_mypy.py \
		--python-version 3.10 packages/agent packages/core-domain

test:
	$(BIN)/pytest tests/unit

test-db:
	$(BIN)/pytest tests/db -m db

test-int:
	$(BIN)/pytest tests/integration -m integration

invariants:
	$(BIN)/python tests/invariants/check_core_domain_pure.py
	$(BIN)/python tests/invariants/check_import_boundaries.py
	$(BIN)/python tests/invariants/check_tenant_id.py
	$(BIN)/python tests/invariants/check_alvo_py39.py

check: lint typecheck test invariants
	@echo "tudo verde"

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
