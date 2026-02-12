#!/bin/bash
# Generate TypeScript types from OpenAPI specification
# Usage: ./scripts/generate-types.sh
#
# Generates the OpenAPI spec from FastAPI source code, then converts
# it to TypeScript types using openapi-typescript.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TYPES_DIR="$PROJECT_ROOT/packages/otel-data-types"
SPEC_FILE="$PROJECT_ROOT/docs/openapi.json"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=== OTel Data API — TypeScript Type Generator ===${NC}"
echo ""

# Step 1: Generate OpenAPI spec from code
echo -e "${BLUE}Step 1: Generating OpenAPI spec from FastAPI source${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found${NC}"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}✗ jq not found. Install with: sudo apt install jq${NC}"
    exit 1
fi

if python3 "$SCRIPT_DIR/generate-openapi-spec.py" -o "$SPEC_FILE"; then
    echo -e "${GREEN}✓ Spec generated: $SPEC_FILE${NC}"
else
    echo -e "${RED}✗ Failed to generate spec${NC}"
    exit 1
fi

# Step 2: Validate JSON
echo ""
echo -e "${BLUE}Step 2: Validating OpenAPI spec${NC}"
if jq empty "$SPEC_FILE" 2>/dev/null; then
    VERSION=$(jq -r '.info.version // "unknown"' "$SPEC_FILE")
    TITLE=$(jq -r '.info.title // "unknown"' "$SPEC_FILE")
    OPENAPI_VER=$(jq -r '.openapi // "unknown"' "$SPEC_FILE")
    PATHS_COUNT=$(jq '.paths | length' "$SPEC_FILE")
    SCHEMAS_COUNT=$(jq '.components.schemas | length' "$SPEC_FILE")
    echo -e "${GREEN}✓ Valid JSON${NC}"
    echo -e "  API: ${TITLE} v${VERSION}"
    echo -e "  OpenAPI: ${OPENAPI_VER}"
    echo -e "  Paths: ${PATHS_COUNT}, Schemas: ${SCHEMAS_COUNT}"
else
    echo -e "${RED}✗ Invalid JSON${NC}"
    exit 1
fi

# Step 3: Generate TypeScript types
echo ""
echo -e "${BLUE}Step 3: Generating TypeScript types${NC}"

if ! command -v npx &> /dev/null; then
    echo -e "${RED}✗ npx not found. Please install Node.js${NC}"
    exit 1
fi

mkdir -p "$TYPES_DIR"
OUTPUT_FILE="$TYPES_DIR/index.d.ts"

# openapi-typescript v7+ works directly with OpenAPI 3.1
if npx openapi-typescript@7.10.1 "$SPEC_FILE" --output "$OUTPUT_FILE" --export-type 2>&1; then
    echo -e "${GREEN}✓ Types generated: $OUTPUT_FILE${NC}"
else
    echo -e "${RED}✗ Failed to generate types${NC}"
    exit 1
fi

# Step 4: Summary
echo ""
echo -e "${BLUE}Step 4: Summary${NC}"
ENDPOINT_COUNT=$(grep -c '"/.*":' "$OUTPUT_FILE" 2>/dev/null || echo "0")
echo -e "  File size: $(du -h "$OUTPUT_FILE" | cut -f1)"
echo -e "  Endpoints: ${ENDPOINT_COUNT}"
echo ""
echo -e "${GREEN}=== Type generation complete! ===${NC}"
echo ""
echo "Generated files:"
echo "  Spec: $SPEC_FILE"
echo "  Types: $OUTPUT_FILE"
echo ""
echo "Next steps:"
echo "  1. Review types: cat $OUTPUT_FILE"
echo "  2. Publish: cd $TYPES_DIR && npm publish"
