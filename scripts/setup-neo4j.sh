#!/bin/bash
# Neo4j Setup Script for Agent Hub
#
# Prerequisites:
#   - Java 21 (OpenJDK): sudo apt install openjdk-21-jdk-headless
#
# This script documents the Neo4j installation for the Graphiti knowledge graph.
# Neo4j is installed as a user-level systemd service.

set -euo pipefail

NEO4J_VERSION="2025.12.1"
NEO4J_HOME="$HOME/neo4j-community-$NEO4J_VERSION"
DOWNLOAD_URL="https://dist.neo4j.org/neo4j-community-$NEO4J_VERSION-unix.tar.gz"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log() { echo -e "${GREEN}[neo4j]${NC} $1"; }
err() { echo -e "${RED}[neo4j]${NC} $1" >&2; }

check_java() {
    if ! command -v java &> /dev/null; then
        err "Java not found. Install with: sudo apt install openjdk-21-jdk-headless"
        exit 1
    fi

    java_version=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [ "$java_version" -lt 17 ]; then
        err "Java 17+ required. Found version $java_version"
        exit 1
    fi
    log "Java $java_version found"
}

download_neo4j() {
    if [ -d "$NEO4J_HOME" ]; then
        log "Neo4j already installed at $NEO4J_HOME"
        return 0
    fi

    log "Downloading Neo4j $NEO4J_VERSION..."
    curl -L -o "/tmp/neo4j-$NEO4J_VERSION.tar.gz" "$DOWNLOAD_URL"

    log "Extracting..."
    tar -xf "/tmp/neo4j-$NEO4J_VERSION.tar.gz" -C "$HOME"
    rm "/tmp/neo4j-$NEO4J_VERSION.tar.gz"

    log "Neo4j installed to $NEO4J_HOME"
}

configure_neo4j() {
    local conf="$NEO4J_HOME/conf/neo4j.conf"

    log "Configuring Neo4j for local development..."

    # Disable auth for local dev
    sed -i 's/^#dbms.security.auth_enabled=false/dbms.security.auth_enabled=false/' "$conf"

    # Disable usage reporting
    sed -i 's/^#dbms.usage_report.enabled=false/dbms.usage_report.enabled=false/' "$conf"

    # Set heap size
    sed -i 's/^#server.memory.heap.initial_size=512m/server.memory.heap.initial_size=512m/' "$conf"
    sed -i 's/^#server.memory.heap.max_size=512m/server.memory.heap.max_size=512m/' "$conf"

    log "Configuration complete"
}

install_service() {
    local service_dir="$HOME/.config/systemd/user"
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local source_service="$script_dir/systemd/neo4j.service"

    mkdir -p "$service_dir"

    # Use symlink pattern consistent with other agent-hub services
    if [ ! -L "$service_dir/neo4j.service" ]; then
        ln -sf "$source_service" "$service_dir/"
        log "Symlinked neo4j.service from scripts/systemd/"
    fi

    systemctl --user daemon-reload
    systemctl --user enable neo4j

    log "Systemd service installed"
}

start_service() {
    log "Starting Neo4j..."
    systemctl --user start neo4j

    # Wait for startup
    local retries=30
    while [ $retries -gt 0 ]; do
        if curl -s http://localhost:7474 > /dev/null 2>&1; then
            log "Neo4j is running at http://localhost:7474"
            log "Bolt endpoint: bolt://localhost:7687"
            return 0
        fi
        sleep 1
        ((retries--))
    done

    err "Neo4j failed to start. Check: journalctl --user -u neo4j"
    exit 1
}

status() {
    if systemctl --user is-active --quiet neo4j; then
        log "Neo4j is running"
        curl -s http://localhost:7474 | python3 -m json.tool
    else
        err "Neo4j is not running"
        exit 1
    fi
}

case "${1:-install}" in
    install)
        check_java
        download_neo4j
        configure_neo4j
        install_service
        start_service
        ;;
    start)
        systemctl --user start neo4j
        log "Neo4j started"
        ;;
    stop)
        systemctl --user stop neo4j
        log "Neo4j stopped"
        ;;
    restart)
        systemctl --user restart neo4j
        log "Neo4j restarted"
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {install|start|stop|restart|status}"
        exit 1
        ;;
esac
