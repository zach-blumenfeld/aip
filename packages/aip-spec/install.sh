#!/usr/bin/env bash
#
# One-command installer for the AIP format: the `aip-spec` CLI (validator, schema, runtime
# block) and the `aip` authoring skill, installed into every agent detected on this machine.
#
#   curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip-spec/main/install.sh | bash
#
# For the runtime too (`aip run`, the client and server), use the installer in
# https://github.com/zach-blumenfeld/aip instead; it pulls this package in.
#
# Idempotent: safe to re-run; it upgrades the package and refreshes the skill.
set -euo pipefail

AIP_SPEC_REF="${AIP_SPEC_REF:-v0.6a1}"

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n'  "$*"; }
warn() { printf '\033[33m!\033[0m %s\n'  "$*" >&2; }

# Freshly installed tool shims land here; make them reachable now.
export PATH="$HOME/.local/bin:$PATH"

# 1. uv, the Python tool manager that installs aip-spec.
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv"

# 2. aip-spec.
info "Installing aip-spec ($AIP_SPEC_REF)…"
uv tool install --force "git+https://github.com/zach-blumenfeld/aip-spec.git@$AIP_SPEC_REF"
hash -r 2>/dev/null || true
ok "aip-spec $(aip-spec --version)"

# 3. The authoring skill, into every detected agent (Claude Code, Cursor, …).
#    Non-fatal: a machine with no agent directory yet should not fail the install.
info "Installing the aip skill…"
aip-spec skill install || warn "skill install skipped: no supported agent detected. Later: 'aip-spec skill install <agent>' (see 'aip-spec skill list') or 'aip-spec skill install --path <skills dir>'."

echo
ok "aip-spec ready. Ask your agent to author or validate an AIP skill; 'aip-spec validate <folder>' checks one by hand."
