#!/bin/bash
#
# Database CLI - Direct PostgreSQL introspection + Alembic migrations
# Simple psql wrapper for cross-project database access
#
# Usage:
#   db tables                    # List all tables
#   db tables --counts           # List with row counts
#   db schema <table>            # Show table schema
#   db count <table>             # Get row count
#   db sample <table> [limit]    # Sample rows (default 10)
#   db sizes                     # Show table and index sizes
#   db indexes [table]           # Show indexes (all or per-table)
#   db query "SELECT ..."        # Run read-only query (writes blocked)
#   db query -t "SELECT ..."     # Run read-only query with plain output
#   db exec "UPDATE ..."         # Run write query (DROP/TRUNCATE blocked)
#   db ddl "CREATE INDEX ..."    # Run safe DDL (CREATE INDEX, ALTER TABLE ADD)
#   db migrate status            # Show current migration state
#   db migrate upgrade           # Apply pending migrations
#   db migrate history [n]       # Show migration history
#   db -P <project> ...          # Target specific project DB
#   db --help                    # Show this help

set -o pipefail

reset_command_guard_shell_state() {
    local guarded_word
    for guarded_word in ${SF_COMMAND_GUARD_WORDS:-}; do
        unset -f "$guarded_word" 2>/dev/null || true
    done
    unset BASH_ENV SF_COMMAND_GUARD_BIN SF_COMMAND_GUARD_WORDS SF_COMMAND_GUARD_PREV_BASH_ENV
}

reset_command_guard_shell_state

# =============================================================================
# CONFIGURATION
# =============================================================================

# Project detection
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")
WORKSPACES_ROOT="${ST_WORKSPACES_ROOT:-/srv/workspaces}"
CURRENT_CONTEXT_ROOT=""
CURRENT_CONTEXT_PROJECT=""

# Source credentials from ~/.env.local
if [[ -f ~/.env.local ]]; then
    # shellcheck disable=SC1090
    source <(grep -E '^(DATABASE_URL|[A-Z0-9_]+_DB_URL|[A-Z0-9_]+_DATABASE_URL)=' ~/.env.local)
fi

# Database connection strings from environment
declare -A DB_URLS=(
    ["summitflow"]="${DATABASE_URL:-postgresql://summitflow_app@localhost:5432/summitflow}"
    ["agent-hub"]="${AGENT_HUB_DB_URL:-postgresql://agent_hub_app@localhost:5432/agent_hub}"
    ["portfolio-ai"]="${PORTFOLIO_AI_DB_URL:-postgresql://portfolio_app@localhost:5432/portfolio_ai}"
    ["a-term"]="${A_TERM_DB_URL:-${DATABASE_URL:-postgresql://summitflow_app@localhost:5432/summitflow}}"
    ["hatchet"]="${HATCHET_DATABASE_URL:-postgresql://db_admin@localhost:5432/hatchet?sslmode=disable}"
)

read_project_id_from_index() {
    local root="$1"
    local index_path="$root/.index.yaml"

    if [[ ! -f "$index_path" ]]; then
        return 1
    fi

    awk '
        /^project:[[:space:]]*/ {
            sub(/^project:[[:space:]]*/, "", $0)
            gsub(/["'"'"']/, "", $0)
            if ($0 != "") {
                print $0
                exit
            }
        }
    ' "$index_path"
}

detect_local_project_context() {
    local candidate="${1:-$PWD}"

    while [[ -n "$candidate" ]]; do
        if [[ -f "$candidate/.index.yaml" ]]; then
            local project_id
            project_id="$(read_project_id_from_index "$candidate")"
            if [[ -n "$project_id" ]]; then
                CURRENT_CONTEXT_ROOT="$candidate"
                CURRENT_CONTEXT_PROJECT="$project_id"
                return 0
            fi
        fi

        if [[ "$candidate" == "/" ]]; then
            break
        fi
        candidate="$(dirname "$candidate")"
    done

    return 1
}

detect_local_project_context "$PWD" || detect_local_project_context "$PROJECT_DIR" || true
if [[ -n "$CURRENT_CONTEXT_PROJECT" ]]; then
    PROJECT_NAME="$CURRENT_CONTEXT_PROJECT"
    PROJECT_DIR="$CURRENT_CONTEXT_ROOT"
fi

resolve_project_root() {
    local project="$1"

    if [[ -n "$CURRENT_CONTEXT_ROOT" && -n "$CURRENT_CONTEXT_PROJECT" && "$CURRENT_CONTEXT_PROJECT" == "$project" ]]; then
        printf '%s\n' "$CURRENT_CONTEXT_ROOT"
        return 0
    fi

    if command -v st >/dev/null 2>&1; then
        local root
        root="$(ST_PROGRESS_ONLY=1 st projects root "$project" 2>/dev/null | head -n 1 | tr -d '\r')"
        if [[ -n "$root" && -d "$root" ]]; then
            printf '%s\n' "$root"
            return 0
        fi
    fi

    if [[ -d "$WORKSPACES_ROOT/projects/$project" ]]; then
        printf '%s\n' "$WORKSPACES_ROOT/projects/$project"
        return 0
    fi

    local manifest_root
    manifest_root="$(
        python3 - "$WORKSPACES_ROOT/projects" "$project" <<'PY'
import json
import sys
from pathlib import Path

workspace_root = Path(sys.argv[1])
project_id = sys.argv[2]

for manifest_path in sorted(workspace_root.glob("*/project.identity.json")):
    try:
        payload = json.loads(manifest_path.read_text())
    except Exception:
        continue

    project = payload.get("project")
    if not isinstance(project, dict):
        continue

    aliases = {
        value
        for key in ("id", "repo_name")
        if isinstance((value := project.get(key)), str) and value
    }
    for key in ("legacy_ids", "repo_aliases"):
        values = project.get(key)
        if isinstance(values, list):
            aliases.update(value for value in values if isinstance(value, str) and value)

    if project_id in aliases:
        print(manifest_path.parent)
        break
PY
    )"
    if [[ -n "$manifest_root" && -d "$manifest_root" ]]; then
        printf '%s\n' "$manifest_root"
        return 0
    fi

    if [[ -d "$HOME/$project" ]]; then
        printf '%s\n' "$HOME/$project"
        return 0
    fi

    return 1
}

# Alembic directories per project
declare -A ALEMBIC_DIRS=(
    ["summitflow"]="$(resolve_project_root summitflow)/backend"
    ["agent-hub"]="$(resolve_project_root agent-hub)/backend"
    ["portfolio-ai"]="$(resolve_project_root portfolio-ai)/backend"
    ["a-term"]="$(resolve_project_root a-term)"
)

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

show_help() {
    cat << 'EOF'
Database CLI - Direct PostgreSQL introspection + Alembic migrations

Usage: db [OPTIONS] COMMAND [ARGS]

Commands:
  tables                    List all tables in current project's database
  tables --counts           List tables with row counts
  schema <table>            Show detailed schema for a table
  count <table>             Get row count for a table
  sample <table> [limit]    Get sample rows (default 10)
  query "SELECT ..."        Execute read-only SQL query
  query -t "SELECT ..."     Execute read-only SQL query with plain output
  exec "UPDATE ..."         Execute write SQL (DROP/TRUNCATE blocked)

Migration Commands:
  migrate status            Show current revision and pending migrations
  migrate upgrade           Apply all pending migrations
  migrate upgrade <rev>     Upgrade to specific revision
  migrate downgrade <rev>   Downgrade to specific revision (use -1 for one step back)
  migrate history [n]       Show last n migrations (default 10)
  migrate create "msg"      Create new migration with message

Options:
  -P, --project <name>      Target specific project (core projects or any <PROJECT>_DB_URL env)
  --help, -h                Show this help

Dump Commands:
  dump schema [file]        Dump schema (DDL only) to file or stdout
  dump data [file]          Dump full database (schema + data) to file or stdout
  dump all-schemas <dir>    Dump schemas for all projects to a directory

Examples:
  db tables                         # List tables in current project
  db tables --counts                # List with row counts
  db schema sessions                # Show sessions table schema
  db migrate status                 # Check migration state
  db migrate upgrade                # Apply pending migrations
  db -P summitflow migrate status   # Check summitflow migrations

Notes:
  - db query enforces read-only (INSERT/UPDATE/DELETE/DROP blocked)
  - db query -t/--plain emits unformatted rows for shell composition
  - db exec allows writes but blocks destructive DDL (DROP/TRUNCATE/GRANT/REVOKE/CREATE)
  - db ddl allows safe DDL: CREATE INDEX, CREATE INDEX IF NOT EXISTS, ALTER TABLE ADD
  - Auto-detects project from repo-local .index.yaml when available
  - When invoked inside a claimed checkout, migration commands prefer that checkout root for the matching project
  - Auxiliary projects use <PROJECT>_DB_URL (example: test2 -> TEST2_DB_URL)
  - Migration commands require alembic in <root>/backend/ or <root>/
EOF
}

error() {
    echo -e "${RED}ERROR:${NC} $1" >&2
    exit 1
}

project_db_env_var() {
    local project="$1"

    if [[ "$project" == "summitflow" ]]; then
        printf 'DATABASE_URL\n'
        return 0
    fi

    local normalized="${project//-/_}"
    printf '%s_DB_URL\n' "${normalized^^}"
}

get_db_url() {
    local project="$1"
    local url="${DB_URLS[$project]}"

    if [[ -n "$url" ]]; then
        DB_URL_RESULT="$url"
        return 0
    fi

    local env_var
    env_var=$(project_db_env_var "$project")
    url="${!env_var:-}"

    if [[ -z "$url" ]]; then
        echo -e "${RED}ERROR:${NC} Unknown project: $project. Set $env_var in ~/.env.local or your environment." >&2
        return 1
    fi

    DB_URL_RESULT="$url"
    return 0
}

run_psql() {
    local query="$1"
    local db_url
    get_db_url "$PROJECT_NAME" || return 1
    db_url="$DB_URL_RESULT"

    psql "$db_url" -t -A -c "$query" 2>&1
}

run_psql_formatted() {
    local query="$1"
    local db_url
    get_db_url "$PROJECT_NAME" || return 1
    db_url="$DB_URL_RESULT"

    psql "$db_url" -c "$query" 2>&1
}

# =============================================================================
# COMMANDS
# =============================================================================

cmd_tables() {
    local include_counts="$1"

    echo -e "${BOLD}Database: ${PROJECT_NAME}${NC}"
    echo ""

    if [[ "$include_counts" == "--counts" ]]; then
        local query="
            SELECT
                schemaname || '.' || relname as table_name,
                n_live_tup as row_count
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY relname;
        "
        run_psql_formatted "$query"
    else
        local query="
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename;
        "
        run_psql "$query" | while read -r line; do
            echo "  $line"
        done
    fi
}

cmd_schema() {
    local table_name="$1"

    if [[ -z "$table_name" ]]; then
        error "Table name required. Usage: db schema <table>"
    fi

    echo -e "${BOLD}Table: ${table_name}${NC}"
    echo ""

    # Columns
    echo -e "${CYAN}Columns:${NC}"
    local col_query="
        SELECT
            column_name,
            data_type,
            CASE WHEN is_nullable = 'YES' THEN 'NULL' ELSE 'NOT NULL' END as nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = '$table_name'
        ORDER BY ordinal_position;
    "
    run_psql_formatted "$col_query"

    # Primary Key
    echo -e "${CYAN}Primary Key:${NC}"
    local pk_query="
        SELECT string_agg(a.attname, ', ' ORDER BY a.attnum)
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = '$table_name'::regclass AND i.indisprimary;
    "
    local pk_result
    pk_result=$(run_psql "$pk_query")
    if [[ -n "$pk_result" ]]; then
        echo "  $pk_result"
    else
        echo "  (none)"
    fi
    echo ""

    # Foreign Keys
    echo -e "${CYAN}Foreign Keys:${NC}"
    local fk_query="
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table,
            ccu.column_name AS foreign_column
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.table_name = '$table_name' AND tc.constraint_type = 'FOREIGN KEY';
    "
    run_psql_formatted "$fk_query"

    # Unique Constraints
    echo -e "${CYAN}Unique Constraints:${NC}"
    local uk_query="
        SELECT
            tc.constraint_name,
            string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position)
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.table_name = '$table_name'
            AND tc.constraint_type = 'UNIQUE'
            AND tc.table_schema = 'public'
        GROUP BY tc.constraint_name;
    "
    run_psql_formatted "$uk_query"

    # Indexes
    echo -e "${CYAN}Indexes:${NC}"
    local idx_query="
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = '$table_name' AND schemaname = 'public';
    "
    run_psql_formatted "$idx_query"
}

cmd_count() {
    local table_name="$1"

    if [[ -z "$table_name" ]]; then
        error "Table name required. Usage: db count <table>"
    fi

    local count
    count=$(run_psql "SELECT COUNT(*) FROM $table_name;")
    echo -e "${table_name}: ${BOLD}${count}${NC} rows"
}

cmd_sample() {
    local table_name="$1"
    local limit="${2:-10}"

    if [[ -z "$table_name" ]]; then
        error "Table name required. Usage: db sample <table> [limit]"
    fi

    run_psql_formatted "SELECT * FROM $table_name LIMIT $limit;"
}

cmd_query() {
    local plain_output="false"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -t|--plain)
                plain_output="true"
                shift
                ;;
            --help|-h)
                echo "Usage: db query [-t|--plain] \"SELECT ...\""
                return 0
                ;;
            *)
                break
                ;;
        esac
    done

    local query="$1"

    if [[ -z "$query" ]]; then
        error "Query required. Usage: db query [-t|--plain] \"SELECT ...\""
    fi

    # Enforce read-only: block destructive SQL statements
    local query_upper
    query_upper=$(echo "$query" | tr '[:lower:]' '[:upper:]')
    if echo "$query_upper" | grep -qE '^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b'; then
        error "Write operations blocked. db query is read-only. Use psql directly for writes."
    fi

    if [[ "$plain_output" == "true" ]]; then
        run_psql "$query"
    else
        run_psql_formatted "$query"
    fi
}

cmd_exec() {
    local query="$1"

    if [[ -z "$query" ]]; then
        error "Query required. Usage: db exec \"UPDATE ...\""
    fi

    # Block destructive DDL — schema changes and privilege escalation.
    # Strip SQL string literals first so keywords inside string payloads
    # (single-quoted or dollar-quoted) don't false-positive.
    local query_stripped query_upper
    query_stripped=$(
        printf '%s' "$query" | perl -0777 -pe "
            s/'(?:''|[^'])*'//gs;
            s/\\\$([A-Za-z_][A-Za-z_0-9]*)\\\$.*?\\\$\\1\\\$//gs;
            s/\\\$\\\$.*?\\\$\\\$//gs;
        "
    )
    query_upper=$(echo "$query_stripped" | tr '[:lower:]' '[:upper:]')
    if echo "$query_upper" | grep -qE '\b(DROP|TRUNCATE|GRANT|REVOKE|CREATE)\b'; then
        error "Destructive DDL blocked by db exec. Use alembic migrations for schema changes."
    fi

    # Show affected-row preview for UPDATE/DELETE
    if echo "$query_upper" | grep -qE '^\s*(UPDATE|DELETE)\b'; then
        local table_name count_query
        if echo "$query_upper" | grep -qE '^\s*DELETE\b'; then
            # Extract table from DELETE FROM <table>
            table_name=$(echo "$query" | sed -nE 's/^\s*DELETE\s+FROM\s+(\S+).*/\1/ip' | head -1)
        elif echo "$query_upper" | grep -qE '^\s*UPDATE\b'; then
            # Extract table from UPDATE <table>
            table_name=$(echo "$query" | sed -nE 's/^\s*UPDATE\s+(\S+).*/\1/ip' | head -1)
        fi

        if [[ -n "$table_name" ]]; then
            # Extract WHERE clause if present
            local where_clause
            where_clause=$(echo "$query" | sed -nE 's/.*\b(WHERE\s+.*)/\1/ip' | head -1)
            # Strip trailing semicolons from WHERE clause
            where_clause=$(echo "$where_clause" | sed 's/;*\s*$//')

            if [[ -n "$where_clause" ]]; then
                count_query="SELECT COUNT(*) FROM $table_name $where_clause"
            else
                count_query="SELECT COUNT(*) FROM $table_name"
            fi

            echo -e "${CYAN}Preview: rows affected:${NC}"
            run_psql_formatted "$count_query"
            echo ""
        fi
    fi

    echo -e "${YELLOW}Executing write query on ${PROJECT_NAME}:${NC}"
    run_psql_formatted "$query"
}

cmd_ddl() {
    local query="$1"

    if [[ -z "$query" ]]; then
        error "Query required. Usage: db ddl \"CREATE INDEX IF NOT EXISTS ...\""
    fi

    # Allow only safe DDL operations
    local query_upper
    query_upper=$(echo "$query" | tr '[:lower:]' '[:upper:]')

    # Allowlist: CREATE INDEX (with optional IF NOT EXISTS), ALTER TABLE ... ADD
    if echo "$query_upper" | grep -qE '^\s*CREATE\s+(UNIQUE\s+)?INDEX\s'; then
        : # allowed
    elif echo "$query_upper" | grep -qE '^\s*ALTER\s+TABLE\s+\S+\s+ADD\s'; then
        : # allowed
    else
        error "Only safe DDL allowed: CREATE INDEX, ALTER TABLE ... ADD. Blocked: DROP, TRUNCATE, CREATE TABLE, etc."
    fi

    echo -e "${YELLOW}Executing DDL on ${PROJECT_NAME}:${NC}"
    run_psql_formatted "$query"
}

cmd_sizes() {
    echo -e "${BOLD}Table Sizes: ${PROJECT_NAME}${NC}"
    echo ""

    local query="
        SELECT
            schemaname || '.' || tablename as table_name,
            pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) as total_size,
            pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) as table_size,
            pg_size_pretty(pg_indexes_size(schemaname || '.' || tablename::regclass)) as index_size
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC;
    "
    run_psql_formatted "$query"
}

cmd_indexes() {
    local table_name="$1"

    if [[ -z "$table_name" ]]; then
        # Show all indexes
        echo -e "${BOLD}Indexes: ${PROJECT_NAME}${NC}"
        echo ""
        local query="
            SELECT
                tablename,
                indexname,
                pg_size_pretty(pg_relation_size(indexname::regclass)) as size
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname;
        "
        run_psql_formatted "$query"
    else
        # Show indexes for specific table
        echo -e "${BOLD}Indexes: ${table_name}${NC}"
        echo ""
        local query="
            SELECT
                indexname,
                indexdef,
                pg_size_pretty(pg_relation_size(indexname::regclass)) as size
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = '$table_name'
            ORDER BY indexname;
        "
        run_psql_formatted "$query"
    fi
}

# =============================================================================
# MIGRATION COMMANDS
# =============================================================================

get_alembic_dir() {
    local project="$1"
    local dir="${ALEMBIC_DIRS[$project]}"

    if [[ -z "$dir" ]]; then
        local project_root
        project_root=$(resolve_project_root "$project" || true)
        if [[ -n "$project_root" ]]; then
            if [[ -d "$project_root/backend/alembic" ]]; then
                dir="$project_root/backend"
            elif [[ -d "$project_root/alembic" ]]; then
                dir="$project_root"
            fi
        fi
    fi

    if [[ -z "$dir" ]]; then
        echo -e "${RED}ERROR:${NC} No alembic config for project: $project. Expected <root>/backend/alembic or <root>/alembic." >&2
        return 1
    fi

    if [[ ! -d "$dir/alembic" ]]; then
        echo -e "${RED}ERROR:${NC} Alembic directory not found: $dir/alembic" >&2
        return 1
    fi

    ALEMBIC_DIR_RESULT="$dir"
    return 0
}

run_alembic() {
    local alembic_dir
    get_alembic_dir "$PROJECT_NAME" || return 1
    alembic_dir="$ALEMBIC_DIR_RESULT"
    local db_url
    get_db_url "$PROJECT_NAME" || return 1
    db_url="$DB_URL_RESULT"
    local project_db_var
    project_db_var="$(project_db_env_var "$PROJECT_NAME")"

    # Prefer project venv alembic so migrations run with project-local deps.
    if [[ -x "$alembic_dir/.venv/bin/alembic" ]]; then
        (cd "$alembic_dir" && env DATABASE_URL="$db_url" "$project_db_var=$db_url" "$alembic_dir/.venv/bin/alembic" "$@") 2>&1
        return $?
    fi

    # Host alembic on PATH
    if command -v alembic &>/dev/null; then
        (cd "$alembic_dir" && env DATABASE_URL="$db_url" "$project_db_var=$db_url" alembic "$@") 2>&1
        return $?
    fi

    # Docker fallback: source config and look up container name
    local summitflow_root
    summitflow_root="$(resolve_project_root summitflow || true)"
    local config_file="${summitflow_root:+$summitflow_root/scripts/lib/dev-standards-config.sh}"
    if [[ -f "$config_file" ]]; then
        # shellcheck disable=SC1090
        source "$config_file"
        local container=""
        for mapping in "${DOCKER_SERVICE_MAP[@]}"; do
            local name="${mapping%%:*}"
            local cname="${mapping#*:}"
            if [[ "$name" == "$PROJECT_NAME" ]]; then
                container="$cname"
                break
            fi
        done

        if [[ -n "$container" ]] && docker inspect "$container" &>/dev/null; then
            echo -e "${YELLOW}(using Docker container: $container)${NC}" >&2
            docker exec -w /app "$container" alembic "$@" 2>&1
            return $?
        fi
    fi

    error "No alembic binary found on host and no Docker container available for $PROJECT_NAME"
}

cmd_migrate() {
    local subcmd="${1:-status}"
    shift || true

    if [[ "$subcmd" == "--help" || "$subcmd" == "-h" ]]; then
        cat << 'EOF'
Usage: db migrate <subcommand> [args]

Subcommands:
  status              Show current revision and pending migrations
  upgrade [rev]       Apply pending migrations or upgrade to revision
  downgrade <rev>     Downgrade to revision (use -1 for one step back)
  history [n]         Show recent migration history
  create "message"    Create a new migration revision
EOF
        return 0
    fi

    case "$subcmd" in
        status)
            cmd_migrate_status
            ;;
        upgrade)
            cmd_migrate_upgrade "$@"
            ;;
        downgrade)
            cmd_migrate_downgrade "$@"
            ;;
        history)
            cmd_migrate_history "$@"
            ;;
        create)
            cmd_migrate_create "$@"
            ;;
        *)
            error "Unknown migrate subcommand: $subcmd. Use: status, upgrade, downgrade, history, create"
            ;;
    esac
}

cmd_migrate_status() {
    echo -e "${BOLD}Migration Status: ${PROJECT_NAME}${NC}"
    echo ""

    # Get current revision
    echo -e "${CYAN}Current:${NC}"
    local current
    current=$(run_alembic current 2>&1)
    if [[ $? -ne 0 ]]; then
        echo -e "  ${RED}Error: $current${NC}"
        return 1
    fi
    # Extract just the revision from alembic output
    local rev
    rev=$(echo "$current" | grep -oE '^[a-f0-9]+' | head -1)
    if [[ -n "$rev" ]]; then
        echo "  $rev"
    else
        echo "  (none - database not initialized)"
    fi
    echo ""

    # Get head revision
    echo -e "${CYAN}Head:${NC}"
    local heads
    heads=$(run_alembic heads 2>&1)
    if [[ $? -ne 0 ]]; then
        echo -e "  ${RED}Error: $heads${NC}"
        return 1
    fi
    local head_rev
    head_rev=$(echo "$heads" | grep -oE '^[a-f0-9]+' | head -1)
    echo "  $head_rev"
    echo ""

    # Check if up to date
    if [[ "$rev" == "$head_rev" ]]; then
        echo -e "${GREEN}✓ Up to date${NC}"
    else
        echo -e "${YELLOW}⚠ Pending migrations${NC}"
        echo ""
        echo -e "${CYAN}Pending:${NC}"
        run_alembic history -r "${rev:-base}:head" 2>&1 | head -10
    fi
}

cmd_migrate_upgrade() {
    local target="${1:-head}"

    echo -e "${BOLD}Upgrading ${PROJECT_NAME} to: ${target}${NC}"
    echo ""

    run_alembic upgrade "$target"
    local status=$?

    if [[ $status -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}✓ Upgrade complete${NC}"
    else
        echo ""
        echo -e "${RED}✗ Upgrade failed${NC}"
        return $status
    fi
}

cmd_migrate_downgrade() {
    local target="$1"

    if [[ -z "$target" ]]; then
        error "Target revision required. Usage: db migrate downgrade <rev> (use -1 for one step back)"
    fi

    echo -e "${YELLOW}WARNING: Downgrading ${PROJECT_NAME} to: ${target}${NC}"
    echo ""

    run_alembic downgrade "$target"
    local status=$?

    if [[ $status -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}✓ Downgrade complete${NC}"
    else
        echo ""
        echo -e "${RED}✗ Downgrade failed${NC}"
        return $status
    fi
}

cmd_migrate_history() {
    local limit="${1:-10}"

    echo -e "${BOLD}Migration History: ${PROJECT_NAME}${NC}"
    echo ""

    run_alembic history --verbose 2>&1 | head -n "$((limit * 4))"
}

cmd_migrate_create() {
    local message="$1"

    if [[ "$message" == "--help" || "$message" == "-h" ]]; then
        echo 'Usage: db migrate create "description"'
        return 0
    fi

    if [[ -z "$message" ]]; then
        error "Message required. Usage: db migrate create \"description\""
    fi

    echo -e "${BOLD}Creating migration: ${message}${NC}"
    echo ""

    run_alembic revision -m "$message"
    local status=$?

    if [[ $status -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}✓ Migration created${NC}"
    else
        echo ""
        echo -e "${RED}✗ Failed to create migration${NC}"
        return $status
    fi
}

# =============================================================================
# MAIN
# =============================================================================

# Parse global options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project|-P)
            PROJECT_NAME="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            break
            ;;
    esac
done

# Get command
COMMAND="${1:-tables}"
shift || true

# Execute command
cmd_dump() {
    local subcmd="${1:-schema}"
    shift 2>/dev/null || true

    case "$subcmd" in
        schema)
            local db_url
            get_db_url "$PROJECT_NAME" || return 1
            db_url="$DB_URL_RESULT"
            local outfile="${1:-}"
            if [[ -n "$outfile" ]]; then
                pg_dump "$db_url" --schema-only --no-owner --no-acl > "$outfile" 2>&1
                echo -e "${GREEN}Schema dumped:${NC} $outfile ($(wc -l < "$outfile") lines)"
            else
                pg_dump "$db_url" --schema-only --no-owner --no-acl 2>&1
            fi
            ;;
        data)
            local db_url
            get_db_url "$PROJECT_NAME" || return 1
            db_url="$DB_URL_RESULT"
            local outfile="${1:-}"
            if [[ -n "$outfile" ]]; then
                pg_dump "$db_url" --no-owner --no-acl > "$outfile" 2>&1
                echo -e "${GREEN}Full dump:${NC} $outfile ($(wc -l < "$outfile") lines)"
            else
                pg_dump "$db_url" --no-owner --no-acl 2>&1
            fi
            ;;
        all-schemas)
            local outdir="${1:-.}"
            mkdir -p "$outdir"
            for proj in summitflow agent-hub portfolio-ai; do
                local url="${DB_URLS[$proj]}"
                if [[ -z "$url" ]]; then continue; fi
                local fname="$outdir/${proj}-schema.sql"
                pg_dump "$url" --schema-only --no-owner --no-acl > "$fname" 2>&1
                local lines
                lines=$(wc -l < "$fname")
                if [[ "$lines" -gt 1 ]]; then
                    echo -e "${GREEN}$proj:${NC} $fname ($lines lines)"
                else
                    echo -e "${RED}$proj:${NC} dump failed — $(head -1 "$fname")"
                fi
            done
            ;;
        *)
            error "Unknown dump subcommand: $subcmd. Use: schema, data, all-schemas"
            ;;
    esac
}

case "$COMMAND" in
    tables)
        cmd_tables "$@"
        ;;
    schema)
        cmd_schema "$@"
        ;;
    count)
        cmd_count "$@"
        ;;
    sample)
        cmd_sample "$@"
        ;;
    query)
        cmd_query "$@"
        ;;
    exec)
        cmd_exec "$@"
        ;;
    ddl)
        cmd_ddl "$@"
        ;;
    sizes)
        cmd_sizes "$@"
        ;;
    indexes)
        cmd_indexes "$@"
        ;;
    migrate|migrations|mig)
        cmd_migrate "$@"
        ;;
    dump)
        cmd_dump "$@"
        ;;
    *)
        error "Unknown command: $COMMAND. Use 'db --help' for usage."
        ;;
esac
