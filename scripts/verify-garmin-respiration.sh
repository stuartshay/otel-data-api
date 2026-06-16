#!/bin/bash
# Verify Garmin activity detail response and the `garmin.activity.detail` log.
#
# Usage:
#   ./scripts/verify-garmin-respiration.sh [ACTIVITY_ID]
#
# What it does:
#   1. Calls the public REST endpoint GET /api/v1/garmin/activities/<id> and
#      prints the respiration fields (avg/min/max) plus a few related fields.
#   2. Optionally queries New Relic Logs (via NerdGraph/NRQL) for the
#      `garmin.activity.detail` event emitted by the API for that activity.
#      This requires the API to be running with LOG_GARMIN_ACTIVITY_DETAIL=true.
#
# Environment variables:
#   API_BASE              REST API base URL
#                         (default: https://api.lab.informationcart.com)
#   NEW_RELIC_API_KEY     New Relic user/personal API key (NRAK...). Optional —
#                         if unset, the script prints the NRQL to run manually.
#   NEW_RELIC_ACCOUNT_ID  New Relic account ID. Required for the NR query.
#   NR_SINCE              NRQL time window (default: "30 minutes ago").
set -euo pipefail

ACTIVITY_ID="${1:-23241368288}"
API_BASE="${API_BASE:-https://api.lab.informationcart.com}"
NR_SINCE="${NR_SINCE:-30 minutes ago}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

# Ensure required dependencies are available before doing anything.
for cmd in curl python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo -e "${RED}✗ Required command not found: ${cmd}${NC}" >&2
    exit 1
  fi
done

echo -e "${BLUE}=== Garmin Respiration Verification ===${NC}"
echo "Activity ID : ${ACTIVITY_ID}"
echo "API base    : ${API_BASE}"
echo ""

# ----------------------------------------------------------------------------
# Step 1: Query the REST API directly
# ----------------------------------------------------------------------------
echo -e "${BLUE}Step 1: REST API response${NC}"
ENDPOINT="${API_BASE}/api/v1/garmin/activities/${ACTIVITY_ID}"

# Use a unique temp file (cleaned up on exit) to avoid collisions / leaking
# response data to a predictable path on shared machines.
resp_file="$(mktemp "${TMPDIR:-/tmp}/garmin_activity_resp.XXXXXX.json")"
trap 'rm -f "$resp_file"' EXIT

http_code=$(curl -sS -o "$resp_file" -w "%{http_code}" "${ENDPOINT}" || true)

if [[ "${http_code}" != "200" ]]; then
  echo -e "${RED}✗ API returned HTTP ${http_code} for ${ENDPOINT}${NC}"
  cat "$resp_file" 2>/dev/null || true
  exit 1
fi

echo -e "${GREEN}✓ HTTP 200${NC} ${ENDPOINT}"
echo ""

python3 - "$ACTIVITY_ID" "$resp_file" <<'PY'
import json
import sys

activity_id = sys.argv[1]
with open(sys.argv[2], encoding="utf-8") as fh:
    data = json.load(fh)

resp_fields = [
    "avg_respiration_rate",
    "min_respiration_rate",
    "max_respiration_rate",
]
context_fields = [
    "activity_id",
    "sport",
    "start_time",
    "track_point_count",
    "avg_heart_rate",
]

print("Context:")
for key in context_fields:
    print(f"  {key:20s}: {data.get(key)}")

print("\nRespiration:")
present = False
for key in resp_fields:
    val = data.get(key)
    if val is not None:
        present = True
    print(f"  {key:20s}: {val}")

print()
if present:
    print("RESULT: API IS returning respiration data for this activity.")
else:
    print("RESULT: API returned NULL respiration — the gap is upstream")
    print("        (database column empty / garmin-sync import did not populate it).")
PY
echo ""

# ----------------------------------------------------------------------------
# Step 2: Query New Relic Logs for the garmin.activity.detail event
# ----------------------------------------------------------------------------
echo -e "${BLUE}Step 2: New Relic Logs (garmin.activity.detail)${NC}"

NRQL="SELECT timestamp, garmin_activity_id, \`response.avg_respiration_rate\`, \`response.min_respiration_rate\`, \`response.max_respiration_rate\` FROM Log WHERE message = 'garmin.activity.detail' AND garmin_activity_id = '${ACTIVITY_ID}' SINCE ${NR_SINCE} LIMIT 20"

if [[ -z "${NEW_RELIC_API_KEY:-}" || -z "${NEW_RELIC_ACCOUNT_ID:-}" ]]; then
  echo -e "${YELLOW}NEW_RELIC_API_KEY / NEW_RELIC_ACCOUNT_ID not set — skipping live query.${NC}"
  echo "Run this NRQL in the New Relic UI (Logs / Query builder):"
  echo ""
  echo "  ${NRQL}"
  echo ""
  echo "Note: the API must be deployed with LOG_GARMIN_ACTIVITY_DETAIL=true and"
  echo "the activity endpoint must have been called at least once in the window."
  exit 0
fi

# Build the GraphQL payload safely with python (escapes the NRQL string).
GQL_PAYLOAD=$(python3 - "$NEW_RELIC_ACCOUNT_ID" "$NRQL" <<'PY'
import json
import sys

account_id, nrql = sys.argv[1], sys.argv[2]
query = (
    "{ actor { account(id: %s) { nrql(query: %s) { results } } } }"
    % (int(account_id), json.dumps(nrql))
)
print(json.dumps({"query": query}))
PY
)

echo "Querying New Relic NerdGraph..."
NR_RESP=$(curl -sS -X POST https://api.newrelic.com/graphql \
  -H "Content-Type: application/json" \
  -H "API-Key: ${NEW_RELIC_API_KEY}" \
  -d "${GQL_PAYLOAD}" || true)

python3 - "${NR_RESP}" <<'PY'
import json
import sys

raw = sys.argv[1]
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    print("✗ Could not parse New Relic response:")
    print(raw)
    sys.exit(1)

if payload.get("errors"):
    print("✗ NerdGraph returned errors:")
    print(json.dumps(payload["errors"], indent=2))
    sys.exit(1)

results = (
    payload.get("data", {})
    .get("actor", {})
    .get("account", {})
    .get("nrql", {})
    .get("results", [])
)

if not results:
    print("No matching log events found in the time window.")
    print("Check that LOG_GARMIN_ACTIVITY_DETAIL=true and the endpoint was hit.")
    sys.exit(0)

print(f"Found {len(results)} log event(s):")
for row in results:
    print(json.dumps(row, indent=2))
PY
