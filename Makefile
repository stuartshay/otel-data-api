# =============================================================================
# otel-data-api Makefile
# =============================================================================

.PHONY: help setup install dev start stop restart clean lint format test docker-build docker-run docker-push all verify db-test db-tables dependencies openapi

.DEFAULT_GOAL := help

# Variables
DOCKER_IMAGE := stuartshay/otel-data-api
DOCKER_TAG := latest
VENV_DIR := venv
PID_FILE := .otel-data-api.pid
LOG_FILE := logs/otel-data-api.log

# Colors
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m

help: ## Show this help message
	@echo "$(GREEN)otel-data-api Makefile Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# Setup and Installation
# =============================================================================

setup: ## Run initial project setup
	@echo "$(YELLOW)Running setup script...$(NC)"
	@bash setup.sh
	@echo "$(GREEN)✓ Setup complete$(NC)"

install: ## Install Python dependencies
	@echo "$(YELLOW)Installing dependencies...$(NC)"
	@test -d $(VENV_DIR) || python3 -m venv $(VENV_DIR)
	@. $(VENV_DIR)/bin/activate && pip install -r requirements.txt
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

install-dev: ## Install development dependencies
	@echo "$(YELLOW)Installing development dependencies...$(NC)"
	@. $(VENV_DIR)/bin/activate && pip install -r requirements.txt
	@. $(VENV_DIR)/bin/activate && pip install pytest pytest-cov pytest-asyncio ruff mypy httpx
	@echo "$(GREEN)✓ Development dependencies installed$(NC)"

clean: ## Clean build artifacts and cache
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@rm -f $(PID_FILE)
	@echo "$(GREEN)✓ Cleaned$(NC)"

clean-all: clean ## Clean everything including venv
	@rm -rf $(VENV_DIR)
	@echo "$(GREEN)✓ Deep clean complete$(NC)"

# =============================================================================
# Development Server
# =============================================================================

dev: ## Start development server with auto-reload (foreground)
	@echo "$(YELLOW)Starting otel-data-api dev server...$(NC)"
	@if [ ! -f .env ]; then \
		echo "$(RED)✗ .env file not found. Run './setup.sh' to create it.$(NC)"; \
		exit 1; \
	fi
	@set -a; . ./.env; set +a; \
	. $(VENV_DIR)/bin/activate && uvicorn run:app --host 0.0.0.0 --port 8080 --reload

start: ## Start server in background
	@echo "$(YELLOW)Starting otel-data-api server...$(NC)"
	@if [ ! -f .env ]; then \
		echo "$(RED)✗ .env file not found. Run './setup.sh' to create it.$(NC)"; \
		exit 1; \
	fi
	@if [ -f $(PID_FILE) ]; then \
		kill $$(cat $(PID_FILE)) 2>/dev/null || true; \
		rm -f $(PID_FILE); \
		sleep 1; \
	fi
	@mkdir -p logs
	@(set -a; . ./.env; set +a; \
	 . $(VENV_DIR)/bin/activate && \
	 uvicorn run:app --host 0.0.0.0 --port 8080 --workers 2 > $(LOG_FILE) 2>&1 & echo $$! > $(PID_FILE))
	@sleep 2
	@if [ -f $(PID_FILE) ] && ps -p $$(cat $(PID_FILE)) > /dev/null 2>&1; then \
		echo "$(GREEN)✓ Server started (PID: $$(cat $(PID_FILE)))$(NC)"; \
		echo "$(GREEN)✓ API: http://localhost:8080$(NC)"; \
		echo "$(GREEN)✓ Docs: http://localhost:8080/docs$(NC)"; \
	else \
		echo "$(RED)✗ Server failed to start. Check $(LOG_FILE)$(NC)"; \
		rm -f $(PID_FILE); \
		exit 1; \
	fi

stop: ## Stop server
	@echo "$(YELLOW)Stopping server...$(NC)"
	@if [ -f $(PID_FILE) ]; then \
		kill $$(cat $(PID_FILE)) 2>/dev/null || true; \
		rm -f $(PID_FILE); \
		echo "$(GREEN)✓ Server stopped$(NC)"; \
	else \
		pkill -f "uvicorn.*run:app" 2>/dev/null || echo "$(YELLOW)No server running$(NC)"; \
	fi

restart: stop start ## Restart server

logs: ## Tail server logs
	@tail -f $(LOG_FILE) 2>/dev/null || echo "$(RED)No log file found$(NC)"

# =============================================================================
# Code Quality
# =============================================================================

lint: ## Run ruff linter
	@echo "$(YELLOW)Running linter...$(NC)"
	@. $(VENV_DIR)/bin/activate && ruff check .
	@echo "$(GREEN)✓ Linting complete$(NC)"

lint-fix: ## Fix linting issues
	@. $(VENV_DIR)/bin/activate && ruff check --fix .

format: ## Format code with ruff
	@. $(VENV_DIR)/bin/activate && ruff format .

format-check: ## Check formatting
	@. $(VENV_DIR)/bin/activate && ruff format --check .

type-check: ## Run mypy type checking
	@. $(VENV_DIR)/bin/activate && mypy app/

# =============================================================================
# Testing
# =============================================================================

test: ## Run pytest tests
	@echo "$(YELLOW)Running tests...$(NC)"
	@. $(VENV_DIR)/bin/activate && pytest tests/
	@echo "$(GREEN)✓ Tests complete$(NC)"

test-cov: ## Run tests with coverage
	@. $(VENV_DIR)/bin/activate && pytest --cov=app --cov-report=term-missing tests/

# =============================================================================
# Database
# =============================================================================

define SCRIPT_DB_TEST
import asyncio, asyncpg, os
async def test():
    conn = await asyncpg.connect(
        host=os.environ["PGBOUNCER_HOST"],
        port=int(os.environ["PGBOUNCER_PORT"]),
        database=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"])
    ver = await conn.fetchval("SELECT version()")
    print(f"Connected: {ver[:50]}...")
    await conn.close()
asyncio.run(test())
endef
export SCRIPT_DB_TEST

define SCRIPT_DB_TABLES
import asyncio, asyncpg, os
async def q():
    conn = await asyncpg.connect(
        host=os.environ["PGBOUNCER_HOST"],
        port=int(os.environ["PGBOUNCER_PORT"]),
        database=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"])
    rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    for r in rows:
        print(f"  {r['tablename']}")
    await conn.close()
asyncio.run(q())
endef
export SCRIPT_DB_TABLES

db-test: ## Test database connection
	@echo "$(YELLOW)Testing database connection...$(NC)"
	@set -a; . ./.env; set +a; \
	. $(VENV_DIR)/bin/activate && \
	python3 -c "$$SCRIPT_DB_TEST"

db-tables: ## List database tables
	@echo "$(YELLOW)Listing database tables...$(NC)"
	@set -a; . ./.env; set +a; \
	. $(VENV_DIR)/bin/activate && \
	python3 -c "$$SCRIPT_DB_TABLES"

# =============================================================================
# Dependencies
# =============================================================================

dependencies: ## Check for outdated Python packages
	@echo "$(YELLOW)Checking for outdated packages...$(NC)"
	@. $(VENV_DIR)/bin/activate && \
	pip list --outdated --format=columns 2>/dev/null || true
	@echo ""
	@echo "$(GREEN)✓ Dependency check complete$(NC)"

# =============================================================================
# OpenAPI
# =============================================================================

openapi: ## Generate OpenAPI schema to output directory
	@echo "$(YELLOW)Generating OpenAPI schema...$(NC)"
	@mkdir -p output
	@set -a; . ./.env; set +a; \
	. $(VENV_DIR)/bin/activate && \
	python3 scripts/generate-openapi-spec.py -o output/openapi.json
	@echo "$(GREEN)✓ OpenAPI schema written to output/openapi.json$(NC)"

# =============================================================================
# Docker
# =============================================================================

docker-build: ## Build Docker image
	@docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .
	@echo "$(GREEN)✓ Built: $(DOCKER_IMAGE):$(DOCKER_TAG)$(NC)"

docker-run: ## Run Docker container
	@docker run -p 8080:8080 --name otel-data-api --rm --env-file .env $(DOCKER_IMAGE):$(DOCKER_TAG)

docker-push: ## Push Docker image
	@docker push $(DOCKER_IMAGE):$(DOCKER_TAG)

# =============================================================================
# Convenience
# =============================================================================

check: lint format-check type-check test ## Run all checks

verify: ## Verify environment
	@echo "Python: $$(python3 --version)"
	@test -d $(VENV_DIR) && echo "$(GREEN)✓ venv exists$(NC)" || echo "$(RED)✗ no venv$(NC)"
	@test -f .env && echo "$(GREEN)✓ .env exists$(NC)" || echo "$(RED)✗ no .env$(NC)"
	@command -v docker >/dev/null 2>&1 && echo "Docker: $$(docker --version)" || echo "Docker: not installed"

health: ## Check API health
	@curl -s http://localhost:8080/health | python -m json.tool

reset: clean-all setup ## Full reset
