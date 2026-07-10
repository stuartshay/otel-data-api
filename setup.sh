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

SONAR_SCANNER_VERSION="${SONAR_SCANNER_VERSION:-8.0.1.6346}"
SONAR_SCANNER_DIR="${SCRIPT_DIR}/.tools/sonar-scanner"

ensure_env_entry() {
    local key="$1"
    local value="$2"

    if grep -q "^${key}=" .env; then
        echo -e "${YELLOW}${key} already configured${NC}"
    else
        printf '%s=%s\n' "$key" "$value" >> .env
        echo -e "${GREEN}✓ Added ${key} to .env${NC}"
    fi
}

install_sonar_scanner() {
    if command -v sonar-scanner &> /dev/null; then
        SONAR_SCANNER_PATH="$(command -v sonar-scanner)"
        echo -e "${GREEN}✓ SonarScanner CLI found: ${SONAR_SCANNER_PATH}${NC}"
        return
    fi

    if [[ -x "${SONAR_SCANNER_DIR}/bin/sonar-scanner" ]]; then
        echo -e "${GREEN}✓ SonarScanner CLI already installed: ${SONAR_SCANNER_DIR}${NC}"
        return
    fi

    local architecture
    local platform
    architecture="$(uname -m)"
    case "$architecture" in
        x86_64 | amd64)
            platform="linux-x64"
            ;;
        aarch64 | arm64)
            platform="linux-aarch64"
            ;;
        *)
            echo -e "${YELLOW}⚠ Unsupported SonarScanner architecture: ${architecture}${NC}"
            echo -e "${YELLOW}  Install sonar-scanner manually before running make sonar.${NC}"
            return
            ;;
    esac

    if ! command -v curl &> /dev/null; then
        echo -e "${YELLOW}⚠ curl is required to install SonarScanner CLI${NC}"
        return
    fi

    if ! command -v unzip &> /dev/null; then
        echo -e "${YELLOW}⚠ unzip is required to install SonarScanner CLI${NC}"
        return
    fi

    local scanner_url
    local download_path
    local extract_dir
    scanner_url="https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-${platform}.zip"
    download_path="$(mktemp)"
    extract_dir="$(mktemp -d)"

    echo -e "${YELLOW}Installing SonarScanner CLI ${SONAR_SCANNER_VERSION}...${NC}"
    curl -fsSL "$scanner_url" -o "$download_path"
    unzip -q "$download_path" -d "$extract_dir"
    rm -rf "$SONAR_SCANNER_DIR"
    mkdir -p "$(dirname "$SONAR_SCANNER_DIR")"
    mv "${extract_dir}/sonar-scanner-${SONAR_SCANNER_VERSION}-${platform}" "$SONAR_SCANNER_DIR"
    rm -f "$download_path"
    rm -rf "$extract_dir"
    echo -e "${GREEN}✓ SonarScanner CLI installed: ${SONAR_SCANNER_DIR}${NC}"
}

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
# shellcheck source=/dev/null
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

echo ""
echo -e "${BLUE}Step 7: Setting up SonarScanner CLI...${NC}"
install_sonar_scanner

# Create .env template
echo ""
echo -e "${BLUE}Step 8: Checking environment configuration...${NC}"
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

# SonarQube
SONAR_HOST_URL=https://sonar.lab.informationcart.com
SONAR_PROJECT_KEY=otel-data-api
SONAR_PROJECT_NAME=otel-data-api
SONAR_TOKEN=
EOF
    echo -e "${GREEN}✓ Template .env created${NC}"
else
    echo -e "${YELLOW}.env file already exists${NC}"
fi

ensure_env_entry "SONAR_HOST_URL" "https://sonar.lab.informationcart.com"
ensure_env_entry "SONAR_PROJECT_KEY" "otel-data-api"
ensure_env_entry "SONAR_PROJECT_NAME" "otel-data-api"
ensure_env_entry "SONAR_TOKEN" ""

# Verify setup
echo ""
echo -e "${BLUE}Step 9: Verifying setup...${NC}"
python -c "import fastapi; import asyncpg; print('✓ Core imports successful')"
echo -e "${GREEN}✓ All imports verified${NC}"

# VS Code settings
echo ""
echo -e "${BLUE}Step 10: Configuring VS Code settings...${NC}"
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
echo "  5. Run Sonar:      make sonar"
echo ""
echo "Before committing:"
echo "  pre-commit run -a"
echo ""
