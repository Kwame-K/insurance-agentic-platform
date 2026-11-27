#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
while read -r name sha; do
  [ -d "../$name" ] || git clone "https://github.com/Kwame-K/$name.git" "../$name"
  git -C "../$name" fetch --all --quiet
  git -C "../$name" checkout --quiet "$sha"
  echo "$name @ ${sha:0:7}"
done < repos.lock
