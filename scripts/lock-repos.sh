#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: > repos.lock
for r in insurance-submission-extractor insurance-data-analyst-agent \
         insurance-rag-assistant underwriting-agent \
         insurance-email-intake insurance-underwriting-ui; do
  if [ -n "$(git -C "../$r" status --porcelain)" ]; then
    echo "Dépôt non propre : $r" >&2; exit 1
  fi
  echo "$r $(git -C "../$r" rev-parse HEAD)" >> repos.lock
done
cat repos.lock