# Thin wrappers around uv so humans and agents run the exact same commands.
.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help install run dev test test-cov lint format typecheck check doctor clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install all dependencies (incl. dev)
	$(UV) sync

run: ## Run RepoCop (the single documented start command)
	$(UV) run repocop

dev: ## Run with auto-reload for development
	$(UV) run uvicorn repocop.main:create_app --factory --reload --host 127.0.0.1 --port 8765

test: ## Run the test suite
	$(UV) run pytest

test-cov: ## Run tests with coverage report
	$(UV) run pytest --cov --cov-report=term-missing

lint: ## Lint (no changes)
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Auto-format and apply safe lint fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck: ## Static type check
	$(UV) run mypy

check: lint typecheck test ## Everything CI runs — run before declaring work done

doctor: ## Verify host prerequisites (python, uv, git, claude)
	@./scripts/doctor.sh

clean: ## Remove caches and build artifacts (keeps data/)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
