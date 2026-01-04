#!/bin/bash
# Backup script for agent-hub
# Usage: ./scripts/backup.sh [backup-name]

set -euo pipefail

PROJECT_DIR="/home/kasadis/agent-hub"
BACKUP_DIR="${PROJECT_DIR}/backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_NAME="${1:-backup}-${TIMESTAMP}"

# Create backup directory
mkdir -p "${BACKUP_DIR}"

# Create backup archive (excludes .venv, node_modules, .next, etc.)
tar --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='backups' \
    -czf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" \
    -C "${PROJECT_DIR}" \
    backend frontend scripts spec CLAUDE.md .gitignore

echo "Backup created: ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
ls -lh "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
