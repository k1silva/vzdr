.PHONY: setup lint fmt typecheck test test-int invariants check db-up db-down clean

VENV := .venv
PIP := $(VENV)/bin/pip
BIN := $(VENV)/bin

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install ruff mypy pytest pytest-cov
	@echo "pronto. ative com: source $(VENV)/bin/activate"

lint:
	$(BIN)/ruff check packages tests

fmt:
	$(BIN)/ruff format packages tests
	$(BIN)/ruff check --fix packages tests

typecheck:
	$(BIN)/mypy packages

test:
	$(BIN)/pytest tests/unit

test-int:
	$(BIN)/pytest tests/integration -m integration

invariants:
	$(BIN)/python tests/invariants/check_core_domain_pure.py
	$(BIN)/python tests/invariants/check_import_boundaries.py
	$(BIN)/python tests/invariants/check_tenant_id.py

check: lint typecheck test invariants
	@echo "tudo verde"

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
