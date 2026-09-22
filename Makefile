.PHONY: setup lint fmt typecheck test test-db test-int invariants check db-up db-down clean

VENV := .venv
PIP := $(VENV)/bin/pip
BIN := $(VENV)/bin

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install ruff mypy pytest pytest-cov
	# driver do Postgres: justificado em specs/core-001-tenancy/plan.md
	$(PIP) install 'psycopg[binary]'
	@echo "pronto. ative com: source $(VENV)/bin/activate"

lint:
	$(BIN)/ruff check packages tests

fmt:
	$(BIN)/ruff format packages tests
	$(BIN)/ruff check --fix packages tests

typecheck:
	$(BIN)/mypy packages
	# mypy nao aceita python_version por modulo (e opcao global), entao o que roda no
	# hypervisor passa por uma segunda invocacao. 3.10 e o piso que o mypy aceita —
	# quem garante a sintaxe de 3.9 e o ruff. Ver ADR-0007.
	$(BIN)/mypy --python-version 3.10 packages/agent packages/core-domain

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
