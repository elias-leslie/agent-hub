#!/bin/bash
#
# Database CLI - Direct PostgreSQL introspection
# Simple psql wrapper for cross-project database access
#
# Usage:
#   db tables                    # List all tables
#   db tables --counts           # List with row counts
#   db schema <table>            # Show table schema
#   db count <table>             # Get row count
#   db sample <table> [limit]    # Sample rows (default 10)
#   db query "SELECT ..."        # Run read-only query
#   db -P <project> ...          # Target specific project DB
#   db --help                    # Show this help

set -o pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

# Project detection
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")

# Source credentials from ~/.env.local
if [[ -f ~/.env.local ]]; then
    # shellcheck disable=SC1090
    source <(grep -E '^(DATABASE_URL|AGENT_HUB_DB_URL|PORTFOLIO_AI_DB_URL|TERMINAL_DB_URL)=' ~/.env.local)
fi

# Database connection strings from environment
declare -A DB_URLS=(
    ["summitflow"]="${DATABASE_URL:-postgresql://summitflow_app@localhost:5432/summitflow}"
    ["agent-hub"]="${AGENT_HUB_DB_URL:-postgresql://agent_hub_app@localhost:5432/agent_hub}"
    ["portfolio-ai"]="${PORTFOLIO_AI_DB_URL:-postgresql://portfolio_app@localhost:5432/portfolio_ai}"
    ["terminal"]="${TERMINAL_DB_URL:-${DATABASE_URL:-postgresql://summitflow_app@localhost:5432/summitflow}}"
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
Database CLI - Direct PostgreSQL introspection

Usage: db [OPTIONS] COMMAND [ARGS]

Commands:
  tables                    List all tables in current project's database
  tables --counts           List tables with row counts
  schema <table>            Show detailed schema for a table
  count <table>             Get row count for a table
  sample <table> [limit]    Get sample rows (default 10)
  query "SELECT ..."        Execute read-only SQL query

Options:
  -P, --project <name>      Target specific project (summitflow, agent-hub, portfolio-ai)
  --help, -h                Show this help

Examples:
  db tables                         # List tables in current project
  db tables --counts                # List with row counts
  db schema sessions                # Show sessions table schema
  db count tasks                    # Count rows in tasks
  db sample messages 5              # Get 5 sample rows
  db query "SELECT id, status FROM tasks LIMIT 5"
  db -P summitflow tables           # List summitflow tables

Notes:
  - Queries are read-only by convention (no enforcement)
  - Auto-detects project from git root directory name
EOF
}

error() {
    echo -e "${RED}ERROR:${NC} $1" >&2
    exit 1
}

get_db_url() {
    local project="$1"
    local url="${DB_URLS[$project]}"

    if [[ -z "$url" ]]; then
        error "Unknown project: $project. Known: ${!DB_URLS[*]}"
    fi

    echo "$url"
}

run_psql() {
    local query="$1"
    local db_url
    db_url=$(get_db_url "$PROJECT_NAME")

    psql "$db_url" -t -A -c "$query" 2>&1
}

run_psql_formatted() {
    local query="$1"
    local db_url
    db_url=$(get_db_url "$PROJECT_NAME")

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
    local query="$1"

    if [[ -z "$query" ]]; then
        error "Query required. Usage: db query \"SELECT ...\""
    fi

    run_psql_formatted "$query"
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
    *)
        error "Unknown command: $COMMAND. Use 'db --help' for usage."
        ;;
esac
