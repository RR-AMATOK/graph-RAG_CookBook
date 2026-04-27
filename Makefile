.DEFAULT_GOAL := help
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

PYTHON ?= python3
# `.venv.nosync` excludes the venv from iCloud Drive sync. iCloud sets
# `UF_HIDDEN` on synced files, which makes Python's site.py silently skip
# editable-install .pth files and breaks `import knowledge_graph`.
# On Linux/CI the `.nosync` suffix is harmless — just an unusual venv name.
VENV ?= .venv.nosync
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

# ─────────────────────────────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ─────────────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────────────
$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

.PHONY: install
install: $(VENV)/bin/activate ## Install project + dev dependencies
	$(PIP) install -e ".[dev]"

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .venv build dist *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +

# ─────────────────────────────────────────────────────────────────────
# Quality gates
# ─────────────────────────────────────────────────────────────────────
.PHONY: lint
lint: ## Run ruff lint + format check
	$(VENV)/bin/ruff check src tests evals
	$(VENV)/bin/ruff format --check src tests evals

.PHONY: format
format: ## Apply ruff auto-format
	$(VENV)/bin/ruff check --fix src tests evals
	$(VENV)/bin/ruff format src tests evals

.PHONY: typecheck
typecheck: ## Run mypy
	$(VENV)/bin/mypy src tests evals

.PHONY: test
test: ## Run pytest
	$(VENV)/bin/pytest

.PHONY: check
check: lint typecheck test ## Run all quality gates

# ─────────────────────────────────────────────────────────────────────
# Local infrastructure (FalkorDB + Qdrant)
# ─────────────────────────────────────────────────────────────────────
.PHONY: up
up: ## Start FalkorDB + Qdrant (docker-compose)
	docker compose up -d
	@echo "FalkorDB: redis://localhost:6390  (host port 6390 → container 6379)"
	@echo "Qdrant:   http://localhost:6333"

.PHONY: down
down: ## Stop FalkorDB + Qdrant
	docker compose down

.PHONY: logs
logs: ## Tail docker-compose logs
	docker compose logs -f

# ─────────────────────────────────────────────────────────────────────
# Pipeline targets (placeholders — implemented in Sprint 2+)
# ─────────────────────────────────────────────────────────────────────
.PHONY: bootstrap
bootstrap: install up ## One-shot: venv + dependencies + local infra
	@echo "Bootstrap complete. Next: make ingest (Sprint 2+)."

.PHONY: ingest
ingest: ## Run ingestion pipeline (Sprint 2+)
	@echo "Not implemented yet — Sprint 2+ deliverable."
	@exit 1

.PHONY: export
export: ## Run multi-format export (Sprint 3+)
	@echo "Not implemented yet — Sprint 3+ deliverable."
	@exit 1

.PHONY: publish
publish: ## Publish graph artifact (Sprint 3+)
	@echo "Not implemented yet — Sprint 3+ deliverable."
	@exit 1

.PHONY: eval
eval: ## Run eval harness against current extraction
	$(VENV)/bin/python -m evals.harness.runner

.PHONY: serve-mcp
serve-mcp: ## Start local MCP server for Claude Code (Sprint 2+)
	@echo "Not implemented yet — Sprint 2+ deliverable."
	@exit 1
