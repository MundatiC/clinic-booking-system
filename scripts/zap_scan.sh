#!/usr/bin/env bash
# OWASP ZAP API scan (DAST) against the docker compose stack, authenticated as staff.
#
#   docker compose up -d --build      # with RATE_LIMIT_ENABLED=false for the scan
#   scripts/zap_scan.sh               # report: zap/report.html, zap/report.json
#
# Imports /openapi.json, spiders and actively attacks every operation (SQLi, XSS,
# path traversal, header checks, ...). Fails on any alert configured as FAIL in
# .zap/rules.tsv (every rule is FAIL; exceptions need a written reason there).
set -euo pipefail

API_URL="${API_URL:-http://api:8000}"          # as seen from the ZAP container
HOST_URL="${HOST_URL:-http://localhost:8000}"  # as seen from this machine
NETWORK="${ZAP_NETWORK:-savannah_default}"
IMAGE="${ZAP_IMAGE:-zaproxy/zap-stable:2.17.0}"
STAFF_EMAIL="${STAFF_EMAIL:-staff@example.com}"
STAFF_PASSWORD="${STAFF_PASSWORD:-reception desk for local testing}"
PYTHON="${PYTHON:-python3}"

token=$(curl -fsS -X POST "$HOST_URL/auth/token" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$STAFF_EMAIL\",\"password\":\"$STAFF_PASSWORD\"}" |
  "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

mkdir -p zap
chmod 777 zap  # the ZAP container runs as a different uid and writes reports here

# Send the bearer token on every request ZAP makes.
auth="-config replacer.full_list(0).description=auth"
auth="$auth -config replacer.full_list(0).enabled=true"
auth="$auth -config replacer.full_list(0).matchtype=REQ_HEADER"
auth="$auth -config replacer.full_list(0).matchstr=Authorization"
auth="$auth -config replacer.full_list(0).regex=false"
auth="$auth -config replacer.full_list(0).replacement=Bearer\ $token"

MSYS_NO_PATHCONV=1 docker run --rm --network "$NETWORK" \
  -v "$(pwd)/zap:/zap/wrk:rw" \
  -v "$(pwd)/.zap/rules.tsv:/zap/wrk/rules.tsv:ro" \
  -v "$(pwd)/.zap/hooks.py:/zap/wrk/hooks.py:ro" \
  "$IMAGE" zap-api-scan.py \
  -t "$API_URL/openapi.json" -f openapi \
  -c rules.tsv -r report.html -J report.json \
  --hook=/zap/wrk/hooks.py -z "$auth"
