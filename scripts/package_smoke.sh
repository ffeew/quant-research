#!/usr/bin/env bash
# Lockfile check, wheel build, and a clean-venv import of quant_research plus py.typed.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

uv lock --check
rm -rf dist
uv build

shopt -s nullglob
wheels=(dist/*.whl)
if [[ ${#wheels[@]} -ne 1 ]]; then
  echo "expected exactly one wheel in dist/, found: ${wheels[*]:-none}" >&2
  exit 1
fi

work="$(mktemp -d)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

uv venv --python 3.12 "$work/venv"
uv pip install --python "$work/venv/bin/python" "${wheels[0]}"
"$work/venv/bin/python" - <<'PY'
import pathlib
import quant_research

installed = pathlib.Path(quant_research.__file__).resolve().parent
marker = installed / "py.typed"
if not marker.is_file():
    raise SystemExit(f"py.typed marker missing from installed wheel: {marker}")
print(f"imported {quant_research.__name__} from {quant_research.__file__}")
print(f"py.typed marker present at {marker}")
PY
