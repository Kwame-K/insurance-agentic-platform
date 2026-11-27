#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose config --quiet
docker compose up --build -d --wait postgres
docker compose run --build --rm data-analyst-agent \
  insurance-data-analyst init-db --seed 20260904
docker compose run --build --rm knowledge-agent \
  insurance-rag ingest --source-dir data/combined --recreate
docker compose up --build -d
docker compose ps
