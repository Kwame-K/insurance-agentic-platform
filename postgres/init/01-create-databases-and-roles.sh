#!/bin/bash
# Runs once, when the PostgreSQL data volume is first initialised.
# Each agent gets a distinct database and login role. PUBLIC cannot connect to
# those databases, so an application role cannot open another agent's database.
set -euo pipefail

: "${EXTRACTOR_DB_PASSWORD:?EXTRACTOR_DB_PASSWORD is required}"
: "${UNDERWRITING_DB_PASSWORD:?UNDERWRITING_DB_PASSWORD is required}"
: "${KNOWLEDGE_DB_PASSWORD:?KNOWLEDGE_DB_PASSWORD is required}"

run_sql() {
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres "$@"
}

create_app_database() {
  local role="$1" database="$2" password="$3"

  echo "CREATE ROLE ${role} LOGIN PASSWORD :'password';" | run_sql -v password="$password"
  echo "CREATE DATABASE ${database} OWNER ${role};" | run_sql
  echo "REVOKE ALL ON DATABASE ${database} FROM PUBLIC;" | run_sql
}

create_app_database extractor_app extractor "$EXTRACTOR_DB_PASSWORD"
create_app_database underwriting_app underwriting "$UNDERWRITING_DB_PASSWORD"
create_app_database knowledge_app knowledge "$KNOWLEDGE_DB_PASSWORD"

# The Knowledge Agent will use pgvector in a later migration.
echo "CREATE EXTENSION IF NOT EXISTS vector;" |
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname knowledge

echo "Created databases: extractor, underwriting, knowledge."
