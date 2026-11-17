#!/usr/bin/env bash
# A fresh virtual environment installs this package (and with it Relate, `relate-db` from PyPI)
# and compiles a program: the proof of the plan's L3 (aip#29), kept by L5 for the one package,
# run by CI on every push.
#
#   scripts/fresh-venv.sh [PROGRAM]      default: examples/language/billing-support
#
# It creates a venv in a temporary directory, installs `agent-instruction-protocol` from this
# checkout, compiles the program to a bundle with `aip compile`, exports the bundle to a
# directory, compiles that, and checks the two bundle ids agree. Then it starts `aip server` from
# that install on a store of its own, and checks that it answers, that the four procedures the
# package ships are in its catalog, and that the program publishes: what a checkout's tests cannot
# show, since the wheel must carry the shipped bundles for any of it to work. Nothing is left
# behind, and nothing of this machine's `aip config` is read. Exit 0 when every step passes.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
program="${1:-$root/examples/language/billing-support}"
work=$(mktemp -d)
server=""
# `wait` answers with the stopped server's status (143, it was sent TERM); under `set -e` that
# would end the trap, and the script, with it, after every check has passed.
cleanup() { if [ -n "$server" ]; then kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true; fi; rm -rf "$work"; }
trap cleanup EXIT
export AIP_HOME="$work/home" AIP_CONFIG="$work/config.json"

uv venv --quiet "$work/venv"
uv pip install --quiet --python "$work/venv" "$root"

if [ -x "$work/venv/bin/aip" ]; then bin="$work/venv/bin"; else bin="$work/venv/Scripts"; fi
aip="$bin/aip"
python="$bin/python"
bundle_id() { "$aip" compile --check --json "$1" | "$python" -c 'import json, sys; print(json.load(sys.stdin)["bundle_id"])'; }

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

# The server, from the install: a free port, an empty config file, a store in the temp directory.
port=$("$python" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
: > "$work/server.toml"
"$aip" server --config "$work/server.toml" --path "$work/store.rl" --port "$port" > "$work/server.log" 2>&1 &
server=$!
"$python" - "$port" "$work/server.log" <<'PY'
import json, sys, time, urllib.request
port, log = sys.argv[1], sys.argv[2]
for _ in range(100):
    try:
        health = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2))
        break
    except OSError:
        time.sleep(0.2)
else:
    sys.exit("fresh-venv: aip server did not answer /health; its log:\n" + open(log, encoding="utf-8", errors="replace").read())
if health.get("backend") != "relate":
    sys.exit(f"fresh-venv: /health says {health}")
PY
"$aip" config server "http://127.0.0.1:$port" > /dev/null
shipped=$("$aip" list | "$python" -c 'import sys; print(" ".join(sorted(line.split()[0] for line in sys.stdin if line.strip())))')
if [ "$shipped" != "assist build_procedure edit_procedure make_procedure" ]; then
  echo "fresh-venv: the server's catalog holds [$shipped], not the four procedures the package ships" >&2
  exit 1
fi
"$aip" publish "$program" > /dev/null
echo "fresh-venv: ok, aip server starts from the install, lists the four shipped procedures, and publishes $(basename "$program")"
