> Snapshot of `docs/reference/cli-flags.md` from https://github.com/relatedb/relate at tag `v1.0.0` (Relate 1.0.0, released 2026-11-11), taken 2026-11-11.
> Verbatim copy of the upstream page; nothing below this header is this tree's. The CLI is a release binary (or `curl -sSfL https://relatedb.ai/install.sh | bash`), not part of the `relate-db` wheel; this tree did not run it, so its claims are copied, not verified.

# CLI Flags Reference

## Synopsis

```
relate [OPTIONS] [--database PATH] [QUERY]
relate query [STATEMENT] [--database PATH]
relate <COMMAND> [ARGS]
```

`relate --help` prints the query-run options plus a `Commands:` index of
the commands compiled into the binary. Each command has its own help:
`relate <command> --help` (e.g. `relate clone --help`) prints that
command's synopsis and flags to stdout and exits 0; `relate update --help`
prints the `upgrade` help. A command compiled out of the build keeps its
not-included error and exits 2. Parser usage errors print the failing command's
usage line plus a `Run 'relate <command> --help' for more information.`
hint; the full contract is in
[`docs/api/cli/spec.md`](../api/cli/spec.md#help-and-usage-errors).

Each help page ends with one or two examples. Set `RELATE_HELP_EXAMPLES=0` to
hide them (ADR-0200).

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-d`, `--database PATH` | Store directory (WAL + snapshot), a `.rl` bundle (legacy `.cl` bundles still open, ADR-0517 §5), or `:memory:` (ADR-0200). `-d` is the short form | `:memory:` |
| `QUERY` / `STATEMENT` | One Cypher statement or a `;`-separated list in non-interactive mode (ADR-0200) | _(none — interactive shell on a TTY; statement list from stdin otherwise)_ |

## Options

| Flag | Description |
|------|-------------|
| `-json` | Output results as JSON (indented on a terminal, one compact line when piped — ADR-0240; `--pretty` forces indentation) |
| `-csv` | Output results as CSV |
| `-markdown` | Output results as Markdown |
| `--toon` | Output results as TOON: one `rows[N]{cols}:` header plus one line per row (ADR-0239) |
| `-noheader` | Disable column headers |
| `--pretty` | Indent `json` output even when stdout is not a terminal (ADR-0240) |
| `-mode MODE` | Set output mode (`table`, `csv`, `json`, `jsonl`, `envelope`, `markdown`, `cypher`, `toon`; default table on a terminal, jsonl when stdout is piped or redirected — ADR-0107; `toon` instead of jsonl when agent mode is in effect, ADR-0426). `envelope` prints `{"columns","rows","truncated"}` per result set (ADR-0195). `--format MODE` is the documented alias (ADR-0239) |
| `--format MODE` | Alias of `--mode` (ADR-0239). `--output`/`-o` are errors whose did-you-mean names `--format` |
| `--param N=V` | Bind a Cypher parameter (repeatable) |
| `--fetch-params N=SRC` | Fetch an `http(s)` URL or read a file, parse it as JSON, and bind it as the parameter `N` (repeatable; ADR-0267). Parses in every build; the fetch needs the `fetch-params` Cargo feature (`full` and `agent`, not `minimal`) and fails closed at resolution without it (ADR-0270) |
| `--snapshot-format parquet\|json\|markdown` | Snapshot codec for an **empty** directory (default parquet; json in builds without the `parquet` feature). `parquet` requires the `parquet` Cargo feature (in the `full` bundle, not `agent` or `minimal`); without it the open fails with `parquet snapshot codec is not compiled into this build (enable the "parquet" feature)`. `markdown` turns the empty directory into a vault of `Label/name.md` notes with engine state under `.cypherlite/` (ADR-0406 — see the [storage formats reference](storage-formats.md) and the [Obsidian vault guide](../guides/obsidian-vault.md)). Stored in `manifest.json` (the markdown codec in the `.cypherlite/` sidecar); do not mix codecs. `RELATE_SNAPSHOT_FORMAT` for empty URIs. |
| `--markdown-body-properties LIST` | Body properties of a **markdown** vault (ADR-0460): an ordered default list plus `Label=LIST` per-label entries; entries separated by `;`, names by `,`. The list's first entry renders as the note body (bare), each subsequent one as a `## <property>` section — the heading's first word is a case-insensitive marker (`## Notes` and `## notes Title of the notes` both open the `notes` section, the trailing text becoming its first line with its heading kept: `## Title of the notes`), readable and editable in Obsidian; a listed property that is absent or non-text stays frontmatter. Unconfigured, the body is the single `body` property (ADR-0406). Recorded in the vault's `.cypherlite/manifest.json` at every checkpoint, so later opens need no flag; `RELATE_MARKDOWN_BODY_PROPERTIES` for opens without it. A set configuration on a non-markdown store fails the open. |
| `--wal-dir DIR` | WAL directory (default `<DATABASE>/wal`) |
| `--checkpoint-interval-secs N` | Timed checkpoint period; `0` disables. Persistent URIs only |
| `--durability-mode full\|everysecond\|snapshot` | WAL durability policy (default `full`; `RELATE_DURABILITY_MODE`) |
| `--logical-graph-size-limit SIZE` | Live graph + index cap in logical bytes (`mb`/`mib`/`gb`/`gib`; `0` or unset is unlimited) |
| `--concurrent-logical-workspace-limit SIZE` | Shared logical-workspace pool (`mb`/`mib`/`gb`/`gib`; ADR-0452). A positive value turns admission on. Omit, or an unset `RELATE_CONCURRENT_LOGICAL_WORKSPACE_LIMIT`, leaves it off. `0` is rejected |
| `--max-traversal-depth N` | Largest explicit traversal hop bound a statement may ask for (LABS-610, ADR-0466): an `*1..N` / `{1,N}` bound above it fails at admission with `TraversalDepthExceeded` (syntax error). Values are 1 through 2000; unset uses `RELATE_MAX_TRAVERSAL_DEPTH`, then 500. A safety limit, not a database limit — raising it risks a stack overflow on small-stack platforms |
| `--safe` / `--no-safe` | Opt-in safe mode (LABS-680, ADR-0477), off by default and never auto-detected. Refuses two agent-typical shapes as `SafeModeViolation` (syntax error, exit 6): a `CREATE`/`MERGE` of a new named node without a label, and a `MATCH` read whose final `RETURN`/`WITH` has no `LIMIT` and no reducing aggregate (`collect()` does not count; constant-only returns and write tails are exempt). `--no-safe` negates; `RELATE_SAFE_MODE=1/0` sets the default. Policy, not a database limit |
| `--max-rows N` | Print at most `N` rows per statement; `0` is unlimited. Default: `100` under a detected agent harness with stdout not a terminal, unlimited otherwise (`RELATE_MAX_ROWS`). A cut result warns on stderr and exits `0` (ADR-0196) |
| `--timeout DURATION` | Cancel a statement that runs longer than the bound (ADR-0241): bare number = seconds, `ms`/`s`/`m` suffixes, fractions allowed; `0` disables (default). A timed-out statement prints `Error: query timed out after <duration>` and exits `7` (`code: "timeout"` in the JSON error envelope) |
| `--read-only[=FRESHNESS]` | Open an existing database, reject writes, and do not checkpoint or migrate (ADR-0136; the ADR-0480 spelling). A native directory can be open beside the writer. A `.rl` file opens only while no writer holds it. `:memory:` rejects writes and creates nothing. FRESHNESS is `snapshot` (the default: the frozen state at open) or `live` — tail the WAL of a native directory and reload if a checkpoint leaves a gap (the former `--follow`, ADR-0137; refused for `.rl` and `:memory:`). The value is attached-form only, and the flag is once-only. |
| `--namespace NAME` | Session namespace for the run: `neo4j` (default), `system`, or `system_ontologies`, case-insensitive (ADR-0118). Every statement without `USE` targets it; an unknown name exits 2 with the usage line and a `--help` hint before the store opens. `system_ontologies` is listed but not queryable (ADR-0242): only the ADR-0116 §2 administration commands (`SHOW DATABASES`, `ALTER DATABASE … SET DEFAULT LANGUAGE`) run from there; every other statement routed to it, reads included, exits 6 with 42N17's `This database is not queryable. Use the db.ontology.* procedures on the user database 'neo4j' instead.` Not accepted by `pull`. Example: `relate --database ./store.rl --namespace system -c 'SHOW DATABASES'` |
| `-c, --command CYPHER` | One-shot statement or `;`-separated list (same as positional `QUERY` / `STATEMENT`) |
| `-version` | Show version and license and exit. The text form is two lines — `Relate v<version>` then `License: Apache 2.0 (binary)` (ADR-0432); with `--json` it prints one JSON object with the `license` member instead (ADR-0193, ADR-0432) |

All flags also accept a double-dash form (`--json`, `--csv`, etc.).

### `query` command

`relate query [STATEMENT] [--database PATH]` is the explicit statement
session (ADR-0200), built into every bundle. `-d` / `--database` sets the
store (default `:memory:`) on `query`, on the path-first form, on `pull`,
and on `info`. Session flags (`--json`, `--param`, `--read-only`, …) apply
the same way on `query` and on the path-first form.

```bash
relate query "RETURN 2" --database /tmp/triha/my-db
relate query --database ./friends "MATCH (p:Person) RETURN p.name"
```

### Clone

`relate clone ./mydata ./my-clone` opens the source read-only,
checkpoints that loaded state into the destination, and exits (ADR-0156,
ADR-0282, ADR-0069). Each side is a native directory, or a single-file
bundle when its path ends in `.rl` — so `clone ./mydata ./backup.rl`
exports a directory to a bundle and `clone ./backup.rl ./restored` imports
it back, with no direction or format flag. The source is not written, so a
writer can keep committing to a directory source; a writer-held `.rl`
source fails with a lock error. The clone is the LSN visible when that open
finishes; commits that land afterward are absent. The destination must not
already exist. It is a new store: a snapshot plus an empty WAL (at
`<dest>/wal` for a directory destination). `--wal-dir` on the command names
the source WAL, not the clone's, and is valid only for a directory source —
a bundle embeds its WAL. The clone keeps the source snapshot codec unless
`--to-snapshot-format json|parquet|markdown` names another (ADR-0163),
which transcodes the destination checkpoint (markdown writes a vault of
notes at the destination); the command does not take
`--snapshot-format`. A markdown destination takes
`--markdown-body-properties LIST` (ADR-0460, the query command's flag
grammar); without it a markdown→markdown clone keeps the source's
recorded body-property layout, and the destination sidecar records the
configuration either way.
`:memory:` is refused on both sides. A query or an access flag
(`--read-only`) is not part of the command.

### Durability modes

- `full` (default): append WAL, wait for the group durability barrier, apply,
  then acknowledge. Acknowledged commits survive a crash.
- `everysecond`: append, apply, and acknowledge before the barrier. Dirty WAL
  records are barriered approximately once per second. A crash can lose the
  latest approximately one second of acknowledged writes; slow scheduling,
  storage, or a failed barrier can extend the interval.
- `snapshot`: append, apply, and acknowledge without a WAL barrier. A crash can
  lose every write since the latest completed checkpoint.

Timed checkpoints default to 300 seconds. In `snapshot` mode,
`--checkpoint-interval-secs N` tunes the normal loss window. `0` disables only
the timer; checkpoints still occur explicitly, on clean close, and at the
64 MiB / 10,000-commit WAL thresholds.

## Lifecycle commands

Exit-after lifecycle verbs are positional commands, recognized only as the
first argument. Each needs its Cargo feature compiled in; the default `full`
build (every release binary) has all of them, while the `agent` bundle has
`skill`, `pull`, `push`, `info`, `agent-context`, and the extension program
(the `run` mount plus the `extension` lifecycle verbs; `fetch-params`, the
bundle's remaining feature, gates the `--fetch-params` flag, not a command)
and the `minimal` bundle has none of those. `clone` is built into every
bundle, including `minimal`:

| Command | Feature | Bundles | Description |
|---------|---------|---------|-------------|
| `relate query [STATEMENT] [--database PATH]` | — | all | Run a statement session (ADR-0200). `--database` defaults to `:memory:`. Not an exit-after lifecycle command |
| `relate clone [--wal-dir DIR] [--to-snapshot-format F] SOURCE DEST` | — | all | Copy a database into a new store and exit (ADR-0156, ADR-0282). Each side is a directory, or a `.rl` bundle when its path ends in `.rl`. The cut is the LSN visible on open; the source is not written. The clone keeps the source snapshot codec unless `--to-snapshot-format json\|parquet` transcodes it (ADR-0163). Refused for `:memory:`; `--wal-dir` only with a directory source |
| `relate skill install [--agent NAME] [--force]` | `skill` | full, agent | Install the agent-skill bundle (default: all detected agents) |
| `relate skill list [--agent NAME]` | `skill` | full, agent | Print each target agent's install state and path (ADR-0242) |
| `relate skill check [--agent NAME]` | `skill` | full, agent | Drift-check installed bundles against this binary's bundle; exit 1 on drift (ADR-0242) |
| `relate skill remove [--agent NAME] [--force]` | `skill` | full, agent | Remove the agent-skill bundle |
| `relate upgrade [--yes] [--check]` | `upgrade` | full | Self-update to the latest release listed by the website's `releases.json` (ADR-0250); the download probes the direct release route first and, on a 404 with `GITHUB_TOKEN` set, falls back to the authenticated GitHub API asset route (ADR-0358). `--check` is a read-only current-vs-latest report; `--yes` installs the skill bundle after the upgrade when none is installed yet (no prompt) |
| `relate update [--yes] [--check]` | `upgrade` | full | Alias of `upgrade` |
| `relate telemetry on\|off\|status` | `telemetry` | full | Manage anonymous usage metrics (below) |
| `relate pull [--from FILE] --query Q [--param N=V] --database PATH` | `pull` | full, agent | Pull a Neo4j/Aura subgraph over HTTP Query API v2 into `--database` (union/upsert on source `elementId`; ADR-0200) |
| `relate agent-context [COMMAND]` | `agent-context` | full, agent | Print the compact agent briefing — command index, query-run flags, exit codes; per-command detail with a word (ADR-0242) |
| `relate run fs-to-graph [DIR] [--database PATH] [--max-content-bytes N] [--include-hidden] [--ignore-patterns PAT]` | `extensions` | full, agent | Import a directory tree into a graph as a first-party extension package (ADR-0431 §11; the graph contract ADR-0279/ADR-0157 set). `DIR` defaults to cwd, `--database` to `:memory:`, `--max-content-bytes` to 65536 (larger files keep metadata only). `--ignore-patterns` (repeatable) skips entries by exact name; a trailing `/` matches directories only and prunes the directory entirely. An explicit `--database` exits after the import and does not open the interactive shell; omitting `--database` opens the shell on a TTY with `repl`. The package mounts through `relate run` and needs installing first (`relate extension install fs-to-graph`, ADR-0431) |
| `relate run git-to-graph [DIR] [--database PATH] [--max-commits N] [--max-changeset N] [--since DATE]` | `extensions` | full, agent | Import a git checkout's history into a graph over the same `:File.path` keys as `fs-to-graph`, as a first-party extension package (ADR-0431 §11; the graph contract ADR-0376/ADR-0377/ADR-0392 set). `DIR` defaults to cwd, `--database` to `:memory:`, `--max-commits` (0 = all history) and `--since` (empty = no bound) to no window, `--max-changeset` to 50 (maximum 1000). Merge commits are skipped, `count` on `CO_CHANGED` is set — not incremented — so a re-import is idempotent, and an explicit `--database` exits after the import without opening the interactive shell. An import fails (exit 1) before writing anything when `git log` output exceeds 134217728 bytes or it would write more than 5000000 `CO_CHANGED` pairs; each rows record commits as its own transaction, so a mid-import failure leaves earlier batches committed and re-running the same command completes it; `--max-commits`/`--since` read a smaller window and a lower `--max-changeset` reduces the pairs. The package mounts through `relate run` and needs installing first (`relate extension install git-to-graph`, ADR-0431) |
| `relate info --database PATH [--json]` | `info` | full, agent | Print store metadata gathered by a cold read — no open, no lock, no WAL replay (ADR-0165, ADR-0200): layout, snapshot codec and format version, checkpoint LSN, size on disk, checkpoint-time node/rel counts, and the index/constraint catalog. Key/value table by default, one JSON object with `--json`; `:memory:` is rejected |
| `relate extension init <name> [--lang sh\|py\|ts\|rust]` | `extensions` | full, agent | Scaffold a command-kind extension package into a new directory `<name>/` (ADR-0431 §3): the manifest (mount name, the host's MCP revision, a one-flag `--name` sample table, the `per-batch` commit policy), the language's minimal MCP client generated inline (the transport contract; no published client dependency), a TODO-marked `walk()`, and a README quickstart — installable as is with `extension install <name> --from <name>/`. `--lang` defaults to `py`. An existing directory is a refusal (exit 1); a bad name, a reserved command word, an unknown `--lang` or a missing name is a usage error (exit 2). No store, no network. See the [author guide](../api/extensions/authoring.md) |
| `relate extension install <name> [--github REPO@TAG\|@SHA] [--url URL \| --from DIR] [--version V] [--force] [--re-approve \| --approve SHA]` | `extension-install` | full, agent | Install a command-kind extension package (ADR-0431 §3-§7, ADR-0449). Default source: the signed first-party channel (`extensions.json`, SSHSIG-verified against the pinned release key; the tarball's SHA256 checked against the signed row). `--github` installs a GitHub release pinned to a commit: an untagged `owner/repo` is a usage error; resolution records the tag's commit and the asset's SHA256, and a per-user trust store makes a moved tag or changed asset refuse before any fetch unless re-approved (mutually exclusive with `--url`/`--from`). `--re-approve` re-approves whatever the pin resolves to now; `--approve SHA` re-approves only a resolution whose commit is exactly `SHA` (both require `--github`, mutually exclusive). `--url` is the explicit third-party trust act — https, or plain http to the loopback interface; any other URL is a usage error before any fetch. `--from DIR` is the local-directory trust act — offline/CI/air-gapped; the executable must resolve inside `DIR`, an intermediate-directory symlink is a refusal. `--version V` selects a channel version exactly and is a usage error beside a named source. `--force` clobbers only a foreign (unmarked) target. Every install unpacks into a staged sibling (the decompressed stream capped at 512 MiB at the read), runs the load refusals, writes the provenance marker, then renames into place |
| `relate extension list [--available \| --trust]` | `extensions` (`--available` needs `extension-install`) | full, agent | Print the installed set — name, version, tier, source — offline, never a fetch; `--available` prints the signed channel's catalog instead, and fails closed (exit 1, naming the index URL) when offline (ADR-0431 §9); `--trust` prints the recorded GitHub pins — name, repo, tag, commit, asset SHA256 — from the per-user trust store (ADR-0449). The two flags are mutually exclusive |
| `relate extension remove <name> [--forget-pin]` | `extensions` | full, agent | Remove the installed package; the provenance marker is required — a foreign or unknown directory is a refusal naming what it found, and there is no `--force` (ADR-0431 §3). `--forget-pin` also clears the name's recorded GitHub pin; without it the pin outlives the package, so a reinstall is still compared against it (ADR-0449) |
| `relate extension check <dir>` | `extensions` | full, agent | Run a package directory through the mount's six stages — `manifest`, `executable`, `spawn`, `initialize`, `notifications/initialized`, `tools/list` — printing one line per stage and stopping at the first failure. It opens no store (no `--database` accepted), runs no tool and fetches nothing, so it is safe before installing: exit 2 for the package's declaration and contents, 1 for what it does when run, 0 when it would mount (ADR-0429 §6, ADR-0430 §5, ADR-0447). A clean run closes with one advisory line on the recorded GitHub pin — `approved` / `drifted` / `not from a GitHub source`, read from the provenance marker and the per-user trust store; it never changes the exit code (ADR-0449) |

In a build without a command's feature, the command word is still recognized
and exits 2 with `Error: the '<command>' command is not included in this build
of relate`; `--help` lists only compiled-in commands. See
[Build bundles](../api/cli/spec.md#build-bundles) for the feature table and
how to build the `agent` or `minimal` bundle
(`cargo build -p relate-cli --no-default-features --features agent`).

`skill install` writes `<skills dir>/relate/.relate-installed`. Without
`--force`, `skill install` replaces a destination that is **missing** (the
destination does not exist — `NotFound`; an unreadable or
otherwise-uninspectable destination is **not** missing: any other metadata
error is refused, fail closed), **marker-owned** (`.relate-installed` is a
real regular file;
symlinks are not followed), or **a recognizable relate bundle** (no marker,
but `SKILL.md` frontmatter declares `name: relate` **and** contains a
`version:` line). Any other existing destination — a user-authored or
third-party directory, or a symlinked `<skills dir>/relate` — is refused:
exit 1, directory untouched, stderr
`Error: skill: refusing to touch <dest>: no .relate-installed marker present (directory was not created by relate); pass --force to override`.
`skill remove` is stricter: with no replacement bundle to fall back on it
removes only a marker-owned directory and refuses any unmarked one the same
way. `--force` clobbers `<skills dir>/relate` even when the command would
otherwise refuse it (install: an unmarked, unrecognizable dir; remove: any
unmarked dir), on either command;
`--agent NAME` and `--force` may appear in either order.

After a successful self-replace, `upgrade` refreshes the installed skill bundle
(ADR-0261). It pre-flights each detected agent's `<skills dir>/relate` and
classifies it as **Missing** (absent — `NotFound` only; an unreadable
directory is not Missing: any other metadata error is Foreign, fail closed),
**Owned** (`<dir>/.relate-installed`
present as a regular file; symlinks are not followed), **Legacy** (no marker,
but `SKILL.md` frontmatter declares `name: relate` **and** contains a
`version:` line), or **Foreign** (exists but neither Owned nor Legacy —
including a symlinked dir/marker and a `SKILL.md` declaring `name: relate`
with no `version:` line). **Installed = Owned ∪ Legacy.**

- **Installed** (Owned or Legacy): auto-update with no prompt — one plain
  `skill install` (no `--force`); the child adopts a recognized Legacy bundle
  itself.
- **All targets Missing**: an interactive run asks
  `Install the relate skill? [Y/n] ` (empty = yes); `--yes` installs without
  asking; a non-interactive run without `--yes` prints
  `run: relate skill install` and installs nothing.
- **Foreign is never overwritten**: it is reported with
  `note: {path} is not a recognizable relate skill (no .relate-installed marker, and SKILL.md does not declare name: relate with a version line); leaving it untouched`
  and
  `to replace it with the relate skill bundle, run: relate skill install --force`.
- **Foreign coexists with installed/missing agents**: the refresh falls back to
  one `relate skill install --agent <name>` per non-foreign agent (no
  `--force`), so a forced clobber never reaches the Foreign dir.

The upgrade exit code stays 0 on every post-replace path. `skill install`
adopts a recognizable relate bundle on its own, so the refresh spawns no
`--force`; `skill remove` keeps the strict marker refusal above.

Database paths literally named `query`, `clone`, `skill`, `upgrade`,
`update`, `telemetry`, `pull`, or `info` are passed as the
`--database` value (`relate --database skill` or
`relate --database ./skill`). The first positional is the statement.
`upgrade` sends `Authorization: Bearer $GITHUB_TOKEN` on release-asset
downloads. While the repository is internal the direct route answers 404 and
the token is what selects the authenticated GitHub API asset route (ADR-0358);
it never sends the token on the `releases.json` metadata request (ADR-0250
§5).

### Anonymous usage metrics

The CLI reports anonymous usage metrics (command shapes, feature flags, an
anonymous install id, and a coarse environment tag — never query text, paths,
or data). Builds without the `telemetry` feature (`agent`, `minimal`) never
collect or send anything. Collection defaults to **on** and has a layered opt-out, checked in
this order:

1. `DO_NOT_TRACK=1` (the [consoledonottrack](https://consoledonottrack.com/)
   convention)
2. `RELATE_TELEMETRY` (`0` / `false` / `off` disables)
3. `relate telemetry off`, persisted in
   `<config>/relate/config.json` (`$XDG_CONFIG_HOME/relate/` when
   `$XDG_CONFIG_HOME` is set, non-empty and absolute — a relative or
   empty value is treated as unset — otherwise `~/.config/relate/`)

```bash
relate telemetry status   # e.g. "enabled (default)" / "disabled (DO_NOT_TRACK)"
relate telemetry off      # persist the opt-out; prints the config path
```

`status` prints `<enabled|disabled> (<layer>)`, where the deciding layer is
`default`, `config file`, `RELATE_TELEMETRY`, or `DO_NOT_TRACK`. Only the
standalone `relate` CLI collects metrics; the embedded Rust/Python/WASM
APIs do not. A one-time notice is printed to stderr on the first **enabled**
run, regardless of whether stdin is a terminal, and is suppressed when
telemetry is opted out. `state.json` and `config.json` are written under
`<config>/relate/` via unique `create_new` staging files and are mode
**0600** on unix. Telemetry failures are swallowed — they never affect the
exit code or output.

## Modes of operation

Relate operates in one of three modes, determined automatically. The
`query` verb (ADR-0200) uses the same trichotomy with `--database` instead of
a positional `DATABASE`.

### Interactive mode

When no statement is provided and stdin is a terminal, Relate starts the interactive REPL shell.

```bash
# In-memory database
relate
relate query

# Persistent database directory (Parquet snapshot + WAL)
relate --database ./friends
relate query --database ./friends
```

The shell displays a `cypher>` prompt. Statements end with `;`. Enter `.help`
for `.begin` / `.commit` / `.rollback` / `.quit`. On a TTY the prompt
supports readline-style editing (arrow keys, Home/End) and in-session
history (ADR-0073); builds without the `repl` feature read plain stdin lines
instead.

### Query mode

When a statement is provided (positional `QUERY` / `STATEMENT`, or `-c` /
`--command`), Relate executes it and exits. If the query fails, the
process exits with a non-zero status (see [Exit codes](#exit-codes)).

```bash
relate --database ./friends "MATCH (p:Person) RETURN p.name"
relate query "MATCH (p:Person) RETURN p.name" --database ./friends
```

### Pipe mode

When stdin is not a terminal (i.e., input is being piped), Relate reads and executes all statements from stdin. Statement splitting is comment- and string-aware, so a `;` inside a string literal or a `//` / `/* */` comment does not split a statement.

```bash
relate --database ./friends < setup.cypher
relate query --database ./friends < setup.cypher

echo "MATCH (n) RETURN count(*)" | relate --database ./friends
```

In pipe mode a failing statement stops the batch and the process exits non-zero (see [Exit codes](#exit-codes)). A read error on piped stdin — including invalid UTF-8 — is fatal: nothing is executed and the process exits `1` with `Error: could not read query input from stdin: <reason>` on stderr. There is no size cap on piped stdin.

## Output format flags

Output format flags set the mode before executing the query. Only one format flag should be used at a time.

### `-json`

Outputs results as a JSON array. Each row is a JSON object with column names as keys.

```bash
$ relate --database ./friends -json "MATCH (p:Person) RETURN p.name, p.age"
[
  {"p.name": "Alice", "p.age": 30},
  {"p.name": "Bob", "p.age": 28}
]
```

### `-csv`

Outputs results as comma-separated values with a header row.

```bash
$ relate --database ./friends -csv "MATCH (p:Person) RETURN p.name, p.age"
p.name,p.age
Alice,30
Bob,28
```

### `-markdown`

Outputs results as a Markdown table.

```bash
$ relate --database ./friends -markdown "MATCH (p:Person) RETURN p.name, p.age"
| p.name | p.age |
|--------|-------|
| Alice  | 30    |
| Bob    | 28    |
```

### `-noheader`

Suppresses column headers. Can be combined with any output format.

```bash
$ relate --database ./friends -csv -noheader "MATCH (p:Person) RETURN p.name"
Alice
Bob
```

### `-version`

Prints the version and the binary's license, then exits immediately. The text
form is two lines (ADR-0432); `--json` prints one JSON object instead
(ADR-0193). The license is the name only — `Apache 2.0 (binary)`, scoped to
the binary — never the license text:

```bash
$ relate -version
Relate v1.0.0
License: Apache 2.0 (binary)

$ relate --version --json
{"arch":"aarch64","license":"Apache 2.0 (binary)","name":"relate","os":"macos","version":"1.0.0"}
```

### Output safety

Human-facing output is hardened by default, with no opt-out flag and no
dependence on whether stdout is a terminal:

- `table` / `markdown` escape C0/C1/DEL control characters in cells **and**
  headers (backslash → `\\`, newline/tab/CR → `\n` / `\t` / `\r`, other
  controls → `\u{XXXX}` uppercase, e.g. `\u{1B}`); markdown also escapes `|`
  as `\|`. JSON/JSONL stay byte-exact.
- `csv` quotes fields per RFC 4180 and neutralizes spreadsheet formulas: a
  field whose first character is `=`, `+`, `-`, `@`, tab, or CR is prefixed
  with a single `'`. A negative numeric cell such as `-5` is therefore emitted
  as the text `'-5`.
- `--mode cypher` escapes string-literal controls the lexer understands (`\n`,
  `\t`; CR as `\u000D`; every other control as `\uXXXX`, uppercase) and
  sanitizes identifiers, backticked property keys, and the `// column … omitted`
  comment path using the brace form `\u{XXXX}` (uppercase), so an alias newline
  cannot break the emitted statement or its `//` comment.

See the [output-safety example](../api/cli/examples/output_safety.md).

## Examples

```bash
# Help is the default when no statement is given
relate

# Interactive shell
relate query

# Open or create a persistent directory and start the shell
relate query --database ./friends

# Run a single query
relate --database ./friends "MATCH (p:Person) RETURN p.name ORDER BY p.name"

# Execute a script file
relate query --database ./friends < schema.cypher

# Chain with shell pipes
echo "RETURN 1 + 2 AS result;" | relate query
```

## Snapshot codecs (Relate)

The product CLI writes a **directory**: WAL plus one snapshot codec (ADR-0050). Do not mix Parquet shards and `graph.json` in the same directory.

```bash
# Empty directory → parquet (default)
relate --database ./friends "RETURN 1"

# Empty directory → Relate GraphData in graph.json
relate --snapshot-format json --database ./friends-json "RETURN 1"
# equivalent: RELATE_SNAPSHOT_FORMAT=json relate --database ./friends-json "RETURN 1"
```

Import a GraphData JSON file by copying it to `graph.json` in an empty directory, then opening with `--snapshot-format json`.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (`--help` and `--version` also exit 0) |
| `1` | Runtime failure: database open failure, a query execution failure, or a failed final checkpoint on a persistent database |
| `2` | Usage error: unknown flag, invalid/missing `--mode` or `--namespace` value. A parser usage error prints the relevant command's usage line and a `Run 'relate <command> --help' for more information.` hint; an invalid `--mode`, `--param`, or `--fetch-params` value, `--command` combined with a positional query, a missing query-run flag value, and `skill`'s unknown-agent error print no usage ([Help and usage errors](../api/cli/spec.md#help-and-usage-errors)). An unknown flag close to a real one adds a `Did you mean '<flag>'?` line after the error |
| `5` | Conflict: a write-write conflict, or the database is locked by another opener |
| `6` | Validation error: the statement is rejected (syntax, semantic or type error, including a write on a `--read-only` database) |

Codes 3, 4, 7 and 8 are reserved (shared with `neo4j-cli`). In `json`, `jsonl` and `envelope` modes a failure also prints `{"error":{"code","exit_code","kind","message","retryable"}}` on stdout (a syntax error adds `column` and `source`) ([Query-run errors](../api/cli/spec.md#query-run-errors)).

In query mode and pipe mode, a statement that errors makes the process exit with that statement's code (`6`, `5` or `1`). In pipe mode the run stops at the first failure. Prior durable state is always flushed before a non-zero exit. On every clean exit, a persistent database discards any open explicit transaction and runs a final checkpoint (which also pins the `--snapshot-format` codec); if it fails the process prints `Error: final checkpoint failed: <reason>` and exits `1`. The interactive shell never fails the process for a query error — it reports the error and returns to the prompt — but it exits `1` when that final checkpoint fails.

Full contract: [`docs/api/cli/spec.md`](https://github.com/relatedb/relate/blob/main/docs/api/cli/spec.md).
