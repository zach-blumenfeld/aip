#!/usr/bin/env bash
#
# One-command installer for AIP: the `aip` CLI (run, client, server) with `aip-spec` (the
# format, its validator) as a dependency, and both skills, `aip` (authoring) and
# `aip-runtime` (running published procedures), installed into every agent detected on
# this machine.
#
#   curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash
#
# For the format alone (validate, author; no runtime), use the installer in
# https://github.com/zach-blumenfeld/aip-spec instead.
#
# Idempotent: safe to re-run; it upgrades the package and refreshes both skills.
set -euo pipefail

# The refs to install. `aip` is the `aip-0.5a0` branch until 0.5a0 is tagged here, then
# that tag; `aip-spec` is the format tag `aip`'s pyproject pins. The version-bump checklist
# in README.md moves both.
AIP_REF="${AIP_REF:-aip-0.5a0}"
AIP_SPEC_REF="${AIP_SPEC_REF:-v0.5a0}"

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n'  "$*"; }
warn() { printf '\033[33m!\033[0m %s\n'  "$*" >&2; }

# Freshly installed tool shims land here; make them reachable now.
export PATH="$HOME/.local/bin:$PATH"

# 1. uv, the Python tool manager that installs aip.
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv"

# 2. aip-spec, then aip. `aip` depends on `aip-spec` and would pull it in alone, but a
#    tool install links only its own package's commands, and the authoring skill calls
#    `aip-spec validate`; installing both puts both on PATH.
info "Installing aip-spec ($AIP_SPEC_REF)…"
uv tool install --force "git+https://github.com/zach-blumenfeld/aip-spec.git@$AIP_SPEC_REF"
info "Installing aip ($AIP_REF)…"
uv tool install --force "git+https://github.com/zach-blumenfeld/aip.git@$AIP_REF"
hash -r 2>/dev/null || true
ok "aip, with aip-spec $(aip-spec --version)"

# 3. Both skills, into every detected agent (Claude Code, Cursor, …).
#    Non-fatal: a machine with no agent directory yet should not fail the install.
info "Installing the aip and aip-runtime skills…"
aip skill install || warn "skill install skipped: no supported agent detected. Later: 'aip skill install <agent>' (see 'aip skill list') or 'aip skill install --path <skills dir>'."

echo
ok "aip ready. 'aip --help' lists the commands; 'aip-spec validate <folder>' checks a skill by hand."
