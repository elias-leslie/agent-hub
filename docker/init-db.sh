#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
  SELECT 'CREATE DATABASE hatchet'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'hatchet')\gexec
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname agent_hub <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
