#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${SEARXNG_HOST:-${ST_BROWSER_HOST:-}}"
if [[ -z "$HOST" ]]; then
    echo "Set SEARXNG_HOST or ST_BROWSER_HOST before deploying SearXNG." >&2
    exit 1
fi
PORT="${SEARXNG_PORT:-18900}"
CONTAINER_NAME="${SEARXNG_CONTAINER_NAME:-agenthub-searxng}"
REMOTE_DIR="${SEARXNG_REMOTE_DIR:-/opt/agenthub/searxng}"
IMAGE="${SEARXNG_IMAGE:-searxng/searxng:latest}"
REMOTE_TMP_SETTINGS="/tmp/${CONTAINER_NAME}.settings.yml"
BASE_URL="${SEARXNG_BASE_URL:-http://${HOST}:${PORT}/}"
SECRET="$(
    python3 - <<'PY'
import secrets

print(secrets.token_urlsafe(32))
PY
)"

scp "${SCRIPT_DIR}/searxng.settings.yml" "${HOST}:${REMOTE_TMP_SETTINGS}"

ssh "${HOST}" "set -euo pipefail
sudo mkdir -p '${REMOTE_DIR}'
sudo install -m 0644 '${REMOTE_TMP_SETTINGS}' '${REMOTE_DIR}/settings.yml'
sudo rm -f '${REMOTE_TMP_SETTINGS}'
docker pull '${IMAGE}' >/dev/null
docker rm -f '${CONTAINER_NAME}' >/dev/null 2>&1 || true
docker run -d --restart unless-stopped \
  --name '${CONTAINER_NAME}' \
  -p '${PORT}:8080' \
  -e SEARXNG_BASE_URL='${BASE_URL}' \
  -e SEARXNG_BIND_ADDRESS='0.0.0.0' \
  -e SEARXNG_PORT='8080' \
  -e SEARXNG_SECRET='${SECRET}' \
  -e SEARXNG_LIMITER='false' \
  -e SEARXNG_PUBLIC_INSTANCE='false' \
  -e SEARXNG_IMAGE_PROXY='false' \
  -v '${REMOTE_DIR}:/etc/searxng' \
  '${IMAGE}' >/dev/null
sleep 5
python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen('${BASE_URL}search?q=react+useeffectevent&format=json', timeout=10) as resp:
    payload = json.load(resp)
    first = payload.get('results', [{}])[0]
    print(first.get('url', ''))
    print(len(payload.get('results', [])))
PY
"
