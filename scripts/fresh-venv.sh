#!/usr/bin/env bash
# A fresh virtual environment installs this package and Relate and compiles a program: the proof
# of the plan's L3 (aip#29), kept by L5 for the one package, run by CI when it has a token for
# Relate's release.
#
#   scripts/fresh-venv.sh [PROGRAM]      default: examples/language/billing-support
#
# It creates a venv in a temporary directory, installs `agent-instruction-protocol` from this
# checkout and the Relate wheel (`scripts/install-relate.sh`), compiles the program to a bundle
# with `aip compile`, exports the bundle to a directory, compiles that, and checks the two bundle
# ids agree. Nothing is left behind. Exit 0 when every step passes.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
program="${1:-$root/examples/language/billing-support}"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

uv venv --quiet "$work/venv"
uv pip install --quiet --python "$work/venv" "$root"
"$root/scripts/install-relate.sh" "$work/venv"

if [ -x "$work/venv/bin/aip" ]; then aip="$work/venv/bin/aip"; else aip="$work/venv/Scripts/aip"; fi
bundle_id() { "$aip" compile --check --json "$1" | "$work/venv/bin/python" -c 'import json, sys; print(json.load(sys.stdin)["bundle_id"])'; }

"$aip" --version
"$aip" compile "$program" -o "$work/first.rl"
"$aip" export "$work/first.rl" --out "$work/exported"
"$aip" compile "$work/exported" -o "$work/second.rl"
first=$(bundle_id "$program")
second=$(bundle_id "$work/exported")
if [ "$first" != "$second" ]; then
  echo "fresh-venv: the exported program compiles to $second, the original to $first" >&2
  exit 1
fi
echo "fresh-venv: ok, $program compiles to bundle $first, exports, and compiles again to the same id"
