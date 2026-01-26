#!/bin/bash
#
# Database CLI - Cross-project database introspection
# Calls Agent Hub API for consistent, authenticated access
#
# Usage:
#   db tables                    # List all tables
#   db tables --counts           # List with row counts
#   db schema <table>            # Show table schema
#   db count <table>             # Get row count
#   db sample <table> [limit]    # Sample rows (default 10)
#   db query "SELECT ..."        # Run read-only query
#   db --project <name> ...      # Target specific project DB
#   db --help                    # Show this help
#
# Follows st/dt patterns: project-aware, TOON output, calls API

set -o pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

# Resolve symlinks to find real script location
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

# Agent Hub API base URL
AGENT_HUB_URL="${AGENT_HUB_URL:-http://localhost:8003}"

# Colors (matches dt)
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Project detection (matches dt pattern)
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")

# Project to DB mapping
declare -A PROJECT_DB_MAP=(
    ["summitflow"]="summitflow"
    ["agent-hub"]="agent_hub"
    ["portfolio-ai"]="portfolio_ai"
    ["terminal"]="summitflow"
)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

show_help() {
    cat << 'EOF'
Database CLI - Cross-project database introspection

Usage: db [OPTIONS] COMMAND [ARGS]

Commands:
  tables                    List all tables in current project's database
  tables --counts           List tables with row counts
  schema <table>            Show detailed schema for a table
  count <table>             Get row count for a table
  sample <table> [limit]    Get sample rows (default 10, max 100)
  query "SELECT ..."        Execute read-only SQL query (SELECT only)

Options:
  --project, -P <name>      Target specific project (summitflow, agent-hub, portfolio-ai)
  --raw                     Output raw JSON (default: formatted)
  --help, -h                Show this help

Examples:
  db tables                         # List tables in current project
  db schema sessions                # Show sessions table schema
  db count cost_logs                # Count rows in cost_logs
  db sample messages 5              # Get 5 sample rows from messages
  db query "SELECT id, status FROM sessions LIMIT 5"
  db -P summitflow tables           # List summitflow tables

Notes:
  - All queries are read-only (SELECT only)
  - Results limited to prevent large data transfers
  - Requires Agent Hub API to be running (localhost:8003)
EOF
}

error() {
    echo -e "${RED}ERROR:${NC} $1" >&2
    exit 1
}

warn() {
    echo -e "${YELLOW}WARN:${NC} $1" >&2
}

info() {
    echo -e "${CYAN}$1${NC}"
}

# Call Agent Hub API
api_call() {
    local endpoint="$1"
    local response

    response=$(curl -sf "${AGENT_HUB_URL}/api${endpoint}" 2>&1)
    local exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        if [[ "$response" == *"Connection refused"* ]]; then
            error "Cannot connect to Agent Hub at ${AGENT_HUB_URL}. Is it running?"
        else
            error "API call failed: $response"
        fi
    fi

    echo "$response"
}

# Format table output (TOON-friendly)
format_tables() {
    local json="$1"
    local include_counts="$2"

    if [[ "$RAW_OUTPUT" == "true" ]]; then
        echo "$json"
        return
    fi

    local total
    total=$(echo "$json" | jq -r '.total')

    echo -e "${BOLD}Tables (${total}):${NC}"
    echo ""

    if [[ "$include_counts" == "true" ]]; then
        echo "$json" | jq -r '.tables[] | "\(.name)\t\(.row_count // "-")"' | \
            column -t -s $'\t' | \
            while read -r line; do echo "  $line"; done
    else
        echo "$json" | jq -r '.tables[].name' | \
            while read -r line; do echo "  $line"; done
    fi
}

# Format schema output
format_schema() {
    local json="$1"

    if [[ "$RAW_OUTPUT" == "true" ]]; then
        echo "$json"
        return
    fi

    local table_name
    table_name=$(echo "$json" | jq -r '.name')

    echo -e "${BOLD}Table: ${table_name}${NC}"
    echo ""
    echo -e "${CYAN}Columns:${NC}"
    echo "$json" | jq -r '.columns[] | "  \(.name) \(.type) \(if .nullable then "NULL" else "NOT NULL" end)\(if .primary_key then " [PK]" else "" end)"'

    local pk_count
    pk_count=$(echo "$json" | jq '.primary_keys | length')
    if [[ "$pk_count" -gt 0 ]]; then
        echo ""
        echo -e "${CYAN}Primary Key:${NC}"
        echo "$json" | jq -r '.primary_keys | "  " + join(", ")'
    fi

    local fk_count
    fk_count=$(echo "$json" | jq '.foreign_keys | length')
    if [[ "$fk_count" -gt 0 ]]; then
        echo ""
        echo -e "${CYAN}Foreign Keys:${NC}"
        echo "$json" | jq -r '.foreign_keys[] | "  \(.columns | join(", ")) -> \(.referred_table)(\(.referred_columns | join(", ")))"'
    fi

    local idx_count
    idx_count=$(echo "$json" | jq '.indexes | length')
    if [[ "$idx_count" -gt 0 ]]; then
        echo ""
        echo -e "${CYAN}Indexes:${NC}"
        echo "$json" | jq -r '.indexes[] | "  \(.name // "unnamed"): \(.columns | join(", "))\(if .unique then " [UNIQUE]" else "" end)"'
    fi
}

# Format query results
format_query() {
    local json="$1"

    if [[ "$RAW_OUTPUT" == "true" ]]; then
        echo "$json"
        return
    fi

    local row_count truncated
    row_count=$(echo "$json" | jq -r '.row_count')
    truncated=$(echo "$json" | jq -r '.truncated')

    # Header
    local columns
    columns=$(echo "$json" | jq -r '.columns | join("\t")')
    echo -e "${BOLD}${columns}${NC}" | column -t -s $'\t'

    # Separator
    echo "---"

    # Rows
    echo "$json" | jq -r '.rows[] | map(tostring) | join("\t")' | column -t -s $'\t'

    # Footer
    echo ""
    if [[ "$truncated" == "true" ]]; then
        echo -e "${YELLOW}(${row_count} rows, truncated)${NC}"
    else
        echo -e "${CYAN}(${row_count} rows)${NC}"
    fi
}

# =============================================================================
# COMMANDS
# =============================================================================

cmd_tables() {
    local include_counts="false"

    if [[ "$1" == "--counts" ]]; then
        include_counts="true"
    fi

    local endpoint="/admin/db/tables"
    if [[ "$include_counts" == "true" ]]; then
        endpoint="${endpoint}?include_counts=true"
    fi

    local response
    response=$(api_call "$endpoint")
    format_tables "$response" "$include_counts"
}

cmd_schema() {
    local table_name="$1"

    if [[ -z "$table_name" ]]; then
        error "Table name required. Usage: db schema <table>"
    fi

    local response
    response=$(api_call "/admin/db/tables/${table_name}/schema")
    format_schema "$response"
}

cmd_count() {
    local table_name="$1"

    if [[ -z "$table_name" ]]; then
        error "Table name required. Usage: db count <table>"
    fi

    local response
    response=$(api_call "/admin/db/tables/${table_name}/count")

    if [[ "$RAW_OUTPUT" == "true" ]]; then
        echo "$response"
    else
        local count
        count=$(echo "$response" | jq -r '.count')
        echo -e "${table_name}: ${BOLD}${count}${NC} rows"
    fi
}

cmd_sample() {
    local table_name="$1"
    local limit="${2:-10}"

    if [[ -z "$table_name" ]]; then
        error "Table name required. Usage: db sample <table> [limit]"
    fi

    local response
    response=$(api_call "/admin/db/tables/${table_name}/sample?limit=${limit}")
    format_query "$response"
}

cmd_query() {
    local query="$1"

    if [[ -z "$query" ]]; then
        error "Query required. Usage: db query \"SELECT ...\""
    fi

    # URL encode the query
    local encoded_query
    encoded_query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$query'''))")

    local response
    response=$(api_call "/admin/db/query?q=${encoded_query}")
    format_query "$response"
}

# =============================================================================
# MAIN
# =============================================================================

RAW_OUTPUT="false"

# Parse global options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project|-P)
            PROJECT_NAME="$2"
            shift 2
            ;;
        --raw)
            RAW_OUTPUT="true"
            shift
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
