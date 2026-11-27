#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p scripts/smoke_output
docker compose -f compose.yaml -f compose.demo.yaml run --rm --no-deps \
  -v "$PWD/scripts/smoke_flow.py:/smoke/smoke_flow.py:ro" \
  -v "$PWD/../insurance-submission-extractor/data/synthetic:/samples:ro" \
  -v "$PWD/scripts/smoke_output:/out" \
  underwriting-agent python /smoke/smoke_flow.py
