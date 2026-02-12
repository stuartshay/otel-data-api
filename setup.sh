#!/bin/bash
# OTel Data API Setup Script
# Development environment setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== OTel Data API Environment Setup ==="
echo ""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check Python version
echo -e "${BLUE}Step 1: Checking Python version...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    echo -e "${GREEN}✓ Python ${PYTHON_VERSION} found${NC}"
else
    echo -e "${RED}Python 3 is required but not installed${NC}"
    exit 1
fi

# Create virtual environment
echo ""
echo -e "${BLUE}Step 2: Setting up Python virtual environment...${NC}"
if [[ ! -d "venv" ]]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${YELLOW}Virtual environment already exists${NC}"
fi

# Install dependencies
echo ""
echo -e "${BLUE}Step 3: Installing dependencies...${NC}"
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Install dev dependencies
echo ""
echo -e "${BLUE}Step 4: Installing development tools...${NC}"
DEV_PACKAGES=(
    "pre-commit"
    "pytest"
    "pytest-cov"
    "pytest-asyncio"
    "mypy"
    "httpx"
)

for pkg in "${DEV_PACKAGES[@]}"; do
    if ! pip show "$pkg" &> /dev/null; then
        pip install "$pkg" -q
        echo -e "${GREEN}✓ $pkg installed${NC}"
    else
        echo -e "${YELLOW}$pkg already installed${NC}"
    fi
done

# Setup pre-commit hooks
echo ""
echo -e "${BLUE}Step 5: Setting up pre-commit hooks...${NC}"
if [[ -d ".git" ]]; then
    pre-commit install
    pre-commit install --hook-type pre-push
    echo -e "${GREEN}✓ Pre-commit hooks installed${NC}"
else
    echo -e "${YELLOW}Not a git repository - skipping pre-commit setup${NC}"
fi

# Check Docker
echo ""
echo -e "${BLUE}Step 6: Checking Docker...${NC}"
if command -v docker &> /dev/null; then
    if docker info &> /dev/null; then
        DOCKER_VERSION=$(docker --version | cut -d' ' -f3 | tr -d ',')
        echo -e "${GREEN}✓ Docker ${DOCKER_VERSION} is running${NC}"
    else
        echo -e "${YELLOW}⚠ Docker installed but not running${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Docker not installed (optional)${NC}"
fi

# Create .env template
echo ""
echo -e "${BLUE}Step 7: Checking environment configuration...${NC}"
if [[ ! -f ".env" ]]; then
    cat > .env << 'EOF'
# OTel Data API Configuration

# Database (PgBouncer)
PGBOUNCER_HOST=192.168.1.175
PGBOUNCER_PORT=6432
POSTGRES_DB=owntracks
POSTGRES_USER=development
POSTGRES_PASSWORD=development

# Pool settings
DB_POOL_MIN=2
DB_POOL_MAX=10
DB_CONNECT_TIMEOUT=5

# Server
PORT=8080

# OpenTelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=localhost:4317
OTEL_SERVICE_NAME=otel-data-api
OTEL_SERVICE_NAMESPACE=otel-data-api
OTEL_ENVIRONMENT=development

# OAuth2/Cognito (disabled by default for local dev)
OAUTH2_ENABLED=false
COGNITO_ISSUER=
COGNITO_CLIENT_ID=

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
EOF
    echo -e "${GREEN}✓ Template .env created${NC}"
else
    echo -e "${YELLOW}.env file already exists${NC}"
fi

# Verify setup
echo ""
echo -e "${BLUE}Step 8: Verifying setup...${NC}"
python -c "import fastapi; import asyncpg; print('✓ Core imports successful')"
echo -e "${GREEN}✓ All imports verified${NC}"

# VS Code settings
echo ""
echo -e "${BLUE}Step 9: Configuring VS Code settings...${NC}"
mkdir -p .vscode
cat > .vscode/settings.json << EOF
{
    "python.defaultInterpreterPath": "\${workspaceFolder}/venv/bin/python",
    "python.terminal.activateEnvironment": true,
    "python.analysis.typeCheckingMode": "basic",
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["."],
    "editor.formatOnSave": true,
    "[python]": {
        "editor.defaultFormatter": "charliermarsh.ruff",
        "editor.codeActionsOnSave": {
            "source.fixAll": "explicit",
            "source.organizeImports": "explicit"
        }
    },
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true,
        ".mypy_cache": true,
        ".ruff_cache": true,
        ".pytest_cache": true
    }
}
EOF
echo -e "${GREEN}✓ VS Code settings configured${NC}"

deactivate

echo ""
echo "==================================="
echo -e "${GREEN}Setup Complete!${NC}"
echo "==================================="
echo ""
echo "To start development:"
echo "  1. Activate venv:  source venv/bin/activate"
echo "  2. Run server:     make dev"
echo "  3. View docs:      http://localhost:8080/docs"
echo "  4. Health check:   curl http://localhost:8080/health"
echo ""
echo "Before committing:"
echo "  pre-commit run -a"
echo ""
