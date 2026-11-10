#!/usr/bin/env bash
#
# One-command installer for AIP: the `aip` command (the language's compiler, the runtime, the
# client and the server; one package, `agent-instruction-protocol`, from PyPI) and the `aip`
# skill (how an agent runs a procedure and writes one), installed into every agent detected on
# this machine.
#
#   curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash
#
# Idempotent: safe to re-run; it upgrades the package and refreshes the skill.
# `AIP_REF=<version>` installs that release.
set -euo pipefail

AIP_REF="${AIP_REF:-0.8.0}"

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n'  "$*"; }
warn() { printf '\033[33m!\033[0m %s\n'  "$*" >&2; }

# Freshly installed tool shims land here; make them reachable now.
export PATH="$HOME/.local/bin:$PATH"

# 1. uv, the Python tool manager that installs the package.
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv"

# 2. Before 0.7.0 the runtime was the uv tool `aip`, installed from git. The distribution is
#    `agent-instruction-protocol` now (the command is still `aip`), so that tool goes first.
#    Through 0.8 the language was a second tool, `aip-spec`; since 0.9 it is part of `aip`, so
#    that one goes too.
for old in aip aip-spec; do
  if uv tool list 2>/dev/null | grep -q "^$old v"; then
    info "Removing the $old tool (the package is agent-instruction-protocol now)…"
    uv tool uninstall "$old"
  fi
done

# 3. agent-instruction-protocol, the `aip` command.
info "Installing agent-instruction-protocol ${AIP_REF} (the aip command)…"
uv tool install --force "agent-instruction-protocol[server]==$AIP_REF"
hash -r 2>/dev/null || true

# 3b. Record runs on this machine unless the user already points somewhere: `local` is a server
#     the first `aip run` starts and that stops when idle (`aip config server none` turns it off).
if aip config 2>/dev/null | grep -q '^server: none'; then
  aip config server local >/dev/null && ok "runs are recorded on this machine (aip config server local)"
fi

# 4. The skill, into every detected agent (Claude Code, Codex, Cursor, …): `install` also
#    removes the two skills of 0.8 (`aip-compile`, `aip-runtime`) where an earlier aip recorded
#    installing them, and `prune` removes the ones it has no record of. Non-fatal: a machine
#    with no agent directory yet should not fail the install.
info "Installing the aip skill…"
skills="$(aip skill install 2>&1)" || {
  printf '%s\n' "$skills" >&2
  warn "skill install skipped: no supported agent detected. Later: 'aip skill install <agent>' (see 'aip skill list') or 'aip skill install --path <skills dir>'."
  skills=""
}
pruned="$(aip skill prune 2>&1 | grep '^removed ' || true)"

# 5. What is now on this machine.
echo
tools="$(uv tool list 2>/dev/null)"
ok "agent-instruction-protocol $(printf '%s\n' "$tools" | sed -n 's/^agent-instruction-protocol v//p')  ($(aip --version))"
if [ -n "$skills" ]; then
  # `aip skill install` prints one `installed aip -> <folder>  (<agent>)` line per agent, and
  # `removed <folder>  (...)` for a folder it installed earlier and no longer ships.
  installed="$(printf '%s\n' "$skills" | sed -n 's/^installed .* (\(.*\))$/\1/p' | sort -u | paste -sd ', ' -)"
  [ -n "$installed" ] && ok "the aip skill is installed into: $installed"
  removed="$(printf '%s\n' "$skills" | grep '^removed ' || true)"
  [ -n "$removed" ] && printf '%s\n' "$removed" | while IFS= read -r line; do ok "$line"; done
fi
[ -n "$pruned" ] && printf '%s\n' "$pruned" | while IFS= read -r line; do ok "$line"; done
echo
ok "aip ready. 'aip --help' lists the commands, 'aip skill list' shows which agents have the skill, 'aip list' shows the catalog (make_procedure is in it)."
