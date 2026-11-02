#!/usr/bin/env bash
#
# One-command installer for AIP: the `aip` CLI (run, client, server) and `aip-spec` (the
# format, its validator), both from PyPI, and both skills, `aip-compile` (authoring) and
# `aip-runtime` (running published procedures), installed into every agent detected on
# this machine.
#
#   curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash
#
# Idempotent: safe to re-run; it upgrades both packages and refreshes both skills.
# `AIP_REF=<version>` installs that release of both packages (they always share a version).
set -euo pipefail

AIP_REF="${AIP_REF:-0.7.0}"

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n'  "$*"; }
warn() { printf '\033[33m!\033[0m %s\n'  "$*" >&2; }

# Freshly installed tool shims land here; make them reachable now.
export PATH="$HOME/.local/bin:$PATH"

# 1. uv, the Python tool manager that installs the packages.
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv"

# 2. aip-spec, then agent-instruction-protocol (the `aip` command). `aip` depends on
#    `aip-spec` and would pull it in alone, but a tool install links only its own package's
#    commands, and the authoring skill calls `aip-spec validate`; installing both puts both
#    on PATH.
info "Installing aip-spec ${AIP_REF}…"
uv tool install --force "aip-spec==$AIP_REF"
info "Installing agent-instruction-protocol ${AIP_REF} (the aip command)…"
uv tool install --force "agent-instruction-protocol[server]==$AIP_REF"
hash -r 2>/dev/null || true

# 3. Both skills, into every detected agent (Claude Code, Cursor, …).
#    Non-fatal: a machine with no agent directory yet should not fail the install.
info "Installing the aip-compile and aip-runtime skills…"
skills="$(aip skill install 2>&1)" || {
  printf '%s\n' "$skills" >&2
  warn "skill install skipped: no supported agent detected. Later: 'aip skill install <agent>' (see 'aip skill list') or 'aip skill install --path <skills dir>'."
  skills=""
}

# 4. What is now on this machine.
echo
ok "$(aip --version)"
ok "aip-spec $(aip-spec --version) (format)"
if [ -n "$skills" ]; then
  # `aip skill install` prints one `installed <skill> -> <folder>  (<agent>)` line per skill and
  # agent, and one `removed <folder>  (...)` line per pre-0.7.0 `aip/` skill folder it cleaned up.
  installed="$(printf '%s\n' "$skills" | sed -n 's/^installed .* (\(.*\))$/\1/p' | sort -u | paste -sd ', ' -)"
  [ -n "$installed" ] && ok "skills installed into: $installed"
  printf '%s\n' "$skills" | grep '^removed ' | while IFS= read -r line; do ok "$line"; done
fi
echo
ok "aip ready. 'aip --help' lists the commands; 'aip-spec validate <folder>' checks a skill by hand."
