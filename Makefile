.PHONY: setup lint fmt typecheck test test-py39 test-db test-int invariants check eventos db-up db-papeis db-down clean declaracao-revisao mutacao

VENV := .venv
VENV39 := .venv39
# O interpretador 3.9. Na CI vem do setup-python; localmente, de onde houver.
PY39 ?= python3.9
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
	MYPYPATH=$(MYPY_SRC) $(BIN)/python -m scripts.checar_mypy packages scripts
	# mypy nao aceita python_version por modulo (e opcao global), entao o que roda no
	# hypervisor passa por uma segunda invocacao. 3.10 e o piso que o mypy aceita —
	# quem garante a sintaxe de 3.9 e o ruff. Ver ADR-0007.
	MYPYPATH=$(MYPY_SRC) $(BIN)/python -m scripts.checar_mypy \
		--python-version 3.10 packages/agent packages/core-domain

test:
	$(BIN)/pytest tests/unit

# O que roda no hypervisor, EXECUTADO sob 3.9 — e nao so lido por procuracao. O
# ruff e o check_alvo_py39 leem a intencao; `zip(..., strict=True)` compila em 3.9
# e quebra ao rodar, e so um interpretador 3.9 de verdade o pega — no que os testes
# executam, e so ali (ADR-0007, o limite). Pacotes e testes sao derivados do
# fecho (scripts/fecho_py39.py), e nao listados aqui.
test-py39:
	rm -rf $(VENV39)
	$(PY39) -m venv $(VENV39)
	$(VENV39)/bin/python -c 'import sys; v = sys.version_info[:2]; assert v == (3, 9), v'
	$(VENV39)/bin/pip install -q pytest
	$(BIN)/python scripts/fecho_py39.py pacotes > $(VENV39)/pacotes
	$(BIN)/python scripts/fecho_py39.py testes > $(VENV39)/testes
	for p in $$(cat $(VENV39)/pacotes); do $(VENV39)/bin/pip install -q -e "$$p" || exit 1; done
	$(VENV39)/bin/python -m compileall -q $$(cat $(VENV39)/pacotes)
	PYTHONDONTWRITEBYTECODE=1 $(VENV39)/bin/pytest -p no:cacheprovider $$(cat $(VENV39)/testes)

# Garante o papel da aplicacao antes de testar: sem ele, o teste de isolamento
# rodaria como dono das tabelas e nao provaria nada (ADR-0006).
test-db: db-papeis
	$(BIN)/pytest tests/db -m db

test-int:
	$(BIN)/pytest tests/integration -m integration

invariants:
	$(BIN)/python tests/invariants/check_core_domain_pure.py
	$(BIN)/python tests/invariants/check_import_boundaries.py
	$(BIN)/python tests/invariants/check_tenant_id.py
	$(BIN)/python tests/invariants/check_alvo_py39.py
	$(BIN)/python tests/invariants/check_dsn_guardada.py
	$(BIN)/python tests/invariants/check_pendencias.py
	$(BIN)/python tests/invariants/check_eventos.py
	$(BIN)/python tests/invariants/check_definicao_unica.py
	$(BIN)/python tests/invariants/check_afirmacao_tem_mecanismo.py

# Fora do `invariants` de proposito: aquele e deterministico e roda sem rede.
# Este precisa do corpo do PR, entao tem alvo proprio — e FALHA sem entrada, em
# vez de passar em silencio. Job que deixou de passar a entrada apareceria como
# sucesso, e ausencia de check e indistinguivel de aprovacao.
declaracao-revisao:
	$(BIN)/python tests/invariants/check_declaracao_de_revisao.py

# Confirma que um teste REPROVA quando o controle e desligado. Uso:
#   make mutacao M=caminho/para/mutacoes.json
# Processo novo por rodada, sem bytecode, e verde exigido depois de cada restauro.
mutacao:
	$(BIN)/python -m scripts.mutacao $(M)

check: lint typecheck test invariants
	@echo "tudo verde"

db-up:
	docker compose up -d postgres

# Regera docs/eventos.md a partir das secoes `Eventos` das specs.
eventos:
	$(BIN)/python tests/invariants/check_eventos.py --gerar

db-papeis:
	$(BIN)/python -m scripts.criar_papeis_db

db-down:
	docker compose down

clean:
	rm -rf $(VENV) $(VENV39) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
