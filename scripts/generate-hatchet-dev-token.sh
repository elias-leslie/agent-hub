#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.local}"

cd "$ROOT_DIR"
touch "$ENV_FILE"

bootstrap_token="${HATCHET_CLIENT_TOKEN:-bootstrap-placeholder}"
compose_cmd=(docker compose --env-file "$ENV_FILE")

HATCHET_CLIENT_TOKEN="$bootstrap_token" "${compose_cmd[@]}" up -d agent-hub-db hatchet-migrate hatchet-setup-config >/dev/null
HATCHET_CLIENT_TOKEN="$bootstrap_token" "${compose_cmd[@]}" wait hatchet-setup-config >/dev/null

tenant_id="${HATCHET_TENANT_ID:-}"

if [[ -z "$tenant_id" ]]; then
  tenant_id="$(
    HATCHET_CLIENT_TOKEN="$bootstrap_token" "${compose_cmd[@]}" exec -T agent-hub-db \
      psql -U agent_hub -d hatchet -Atqc \
      "SELECT id FROM \"Tenant\" WHERE name = 'Default' ORDER BY \"createdAt\" DESC LIMIT 1;" 2>/dev/null \
      | tail -n 1
  )"
fi

if [[ -z "$tenant_id" ]]; then
  tenant_id="$(
    HATCHET_CLIENT_TOKEN="$bootstrap_token" "${compose_cmd[@]}" exec -T agent-hub-db \
      psql -U agent_hub -d hatchet -Atqc \
      "SELECT id FROM \"Tenant\" WHERE \"deletedAt\" IS NULL AND slug <> 'internal' ORDER BY \"createdAt\" DESC LIMIT 1;" 2>/dev/null \
      | tail -n 1
  )"
fi

if [[ -z "$tenant_id" ]]; then
  tenant_id="$(
    HATCHET_CLIENT_TOKEN="$bootstrap_token" "${compose_cmd[@]}" logs --no-color hatchet-setup-config 2>/dev/null \
      | grep -Eo 'created tenant [0-9a-f-]+' \
      | awk '{print $3}' \
      | tail -n 1
  )"
fi

if [[ -z "$tenant_id" ]]; then
  echo "Failed to determine the Hatchet tenant ID." >&2
  echo "Check docker compose logs for hatchet-setup-config." >&2
  exit 1
fi

token="$(
  HATCHET_CLIENT_TOKEN="$bootstrap_token" HATCHET_TENANT_ID="$tenant_id" "${compose_cmd[@]}" run --rm -T hatchet-token 2>/dev/null \
    | grep -Eo '[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
    | tail -n 1
)"

if [[ -z "$token" ]]; then
  echo "Failed to generate a Hatchet client token." >&2
  echo "Check docker compose logs for hatchet-setup-config and hatchet-token." >&2
  exit 1
fi

tmp_file="$(mktemp)"
grep -v '^HATCHET_CLIENT_TOKEN=' "$ENV_FILE" > "$tmp_file" || true
grep -v '^HATCHET_TENANT_ID=' "$tmp_file" > "${tmp_file}.next" || true
mv "${tmp_file}.next" "$tmp_file"
printf 'HATCHET_TENANT_ID=%s\n' "$tenant_id" >> "$tmp_file"
printf 'HATCHET_CLIENT_TOKEN=%s\n' "$token" >> "$tmp_file"
mv "$tmp_file" "$ENV_FILE"

echo "Wrote HATCHET_TENANT_ID and HATCHET_CLIENT_TOKEN to $ENV_FILE"
