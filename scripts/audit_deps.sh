#!/usr/bin/env bash
# Audit the locked dependency set (all groups and extras), not an unlocked resolve.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

req="$(mktemp)"
cleanup() { rm -f "$req"; }
trap cleanup EXIT

uv export \
  --quiet \
  --frozen \
  --all-groups \
  --all-extras \
  --no-emit-project \
  --format requirements-txt \
  --output-file "$req"
uv run pip-audit --requirement "$req" --progress-spinner off --disable-pip
