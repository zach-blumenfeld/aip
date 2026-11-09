# Where everything is

For the agent implementing a milestone of the 0.9 plan (issue #1 on `zach-blumenfeld/aip-dev`).
Every pointer here was checked on 2026-11-09. If one is dead, fix it here in the same commit.

## This repository

- You are in a **private mirror** of the public `zach-blumenfeld/aip`. The worktree is
  `~/dev/aip-0.9` on branch `release-0.9.0`; its push remote is `dev` (the mirror). `origin` is
  the public repo: never push there (AGENTS.md, "This is the private 0.9 mirror").
- **The 0.8 code you are replacing is in this same tree**: the runtime under `src/aip/`, the format
  under `packages/aip-spec/`, the server under `src/aip/server/`, the Neo4j backend at
  `src/aip/server/backends/neo4j.py`, the skills under `skills/`, the examples under `examples/`.
  AGENTS.md's repo map describes it. Read the piece you replace before replacing it; the records,
  the governance queries and the HTTP contract carry over in shape.
- **A Relate backend already exists as a reference**: branch `cypherlite-backend` on the mirror
  (`git show cypherlite-backend:src/aip/server/backends/cypherlite.py`), written against
  CypherLite 0.13 and sharing the Neo4j backend's Cypher. The Python API has moved since (typed
  ABI v2 in 0.16); use it for shape, not for calls.
- **The language**: `docs/language/spec.md` (the law), `docs/language/runtime.md`,
  `docs/language/limitations.md`, `docs/language/no-expressions.md`, `docs/language/end-to-end.md`,
  `docs/language/plan-questions.md` (the 26 decisions and why). Programs under
  `examples/language/`. The VS Code grammar under `editors/vscode`.
- The design archive is the private repo `zach-blumenfeld/aip-lang` (copied at its commit
  9845671). Nothing there is newer than this tree.

## The console

`zach-blumenfeld/aip-console-dev`, a private mirror of `zach-blumenfeld/aip-console`; the 0.9
branch is `console-0.9.0`. Local checkout `~/dev/aip-inspector` with remote `dev` pointing at the
mirror. Its AGENTS.md describes the launcher, the API client and the e2e harness; the harness runs
the sibling `aip` checkout from `AIP_REPO`, which for 0.9 is `~/dev/aip-0.9`.

## Relate (formerly CypherLite)

Embedded property-graph engine with Cypher, Neo4j Labs, Apache 2.0. **Unreleased and private;
nothing mentioning it leaves the mirrors.**

| What | Where | Note |
|---|---|---|
| Source and releases | `github.com/neo4j-labs/cypherlite` | visibility is *internal*: web fetches 404; `gh api repos/neo4j-labs/cypherlite/...` works with Zach's login. Moving to `github.com/relatedb/relate` (404 today). |
| Pinned release | **v0.16.1**, 2026-11-04 | the last release under the old name. Wheels: `neo4j_cypherlite-0.16.1-cp39-abi3-{macosx_10_12_x86_64, macosx_11_0_arm64, manylinux2014_x86_64, manylinux2014_aarch64, win_amd64}.whl` on the release's assets. **Install with `scripts/install-relate.sh`** (into `.venv`, or into the environment it is given): it fetches the platform's wheel through the GitHub API (`gh` logged in or `GH_TOKEN`; the plain download URL answers 404 while the repository is internal), checks its sha256 against the five pinned in the script (the release's `SHA256SUMS` covers only the CLI binaries), caches it under `~/.cache/aip/relate/`, and runs `uv pip install`. Not declared in any `pyproject.toml`: `uv lock` would have to fetch it and cannot (L3's note on open item 2). **Import name `cypherlite`.** CI installs it only when the secret `RELATE_GH_TOKEN` is set; otherwise the bundle tests skip. |
| The rename | main branch | `surfaces/relate-python/pyproject.toml` is already `relate-db`, module `relate`; the CLI is `relate`; bundles are `.rl`. The next release ships under those names. `aip_spec/relate.py` is the one module that imports the engine (`relate`, else `cypherlite`) and names bundles `.rl`; since v0.16.1 recognises its single-file form by the `.cl` suffix alone, it writes beside the target as `<name>.rl.tmp.cl` and renames, and opens an `.rl` through a temporary `.cl` link. Both go when the rename ships. |
| The CLI binary | release assets `cypherlite-{darwin,linux}-{arm64,amd64}`, `cypherlite-windows-amd64.exe` | in `SHA256SUMS`. `cypherlite query --database x.rl "..."` does not open an `.rl` at v0.16.1 (it is read as a directory); copy or link the file to `x.cl` first, or use `aip_spec.relate.open` from Python. |
| Docs site | https://neo4j-labs.github.io/cypherlite/ and https://relatedb.ai/ | public. `llms.txt` at either root is the whole reference in one file. |
| Reference docs, snapshotted at v0.16.1 | `docs/language/relate/` in this tree | `python-library.md` (connect, execute, parameters, `read_only=True`, Arrow), `storage-formats.md` (directory, `.cl`/`.rl` single file, codecs, format version), `cli-flags.md` (`--load`, `--read-only`, `clone`, `pull`, `push`, `serve`), `cypher-syntax.md`, `limitations.md`, `llms.txt`. Prefer these to live fetches; refresh them when the pin moves. |
| Repo docs not snapshotted | `docs/adr/`, `docs/api/python/`, `docs/guides/backup-restore.md`, `docs/engine-architecture.md` | via `gh api repos/neo4j-labs/cypherlite/contents/<path>?ref=v0.16.1`, base64 in `.content`. |
| Local wheel cache | `~/.cache/uv/archive-v0/rTrDDOAv8O-PEvqN/` | **CypherLite 0.13.0, stale.** Do not use it as the reference. The 0.16.1 wheels `install-relate.sh` fetched are under `~/.cache/aip/relate/`. |
| Python API, verified at v0.16.1 | `python-library.md` | `cypherlite.connect(path, read_only=False)`; a `.cl` path is one file, any other path a directory; `read_only=True` refuses writes (`WriteOnReadOnlyAccessDatabase`); `properties(n)`, `labels(n)`, `type(e)`, `UNWIND $rows ... SET n = r` with map parameters, list and string properties (tabs, newlines and NUL included) all work; no map-valued properties, no binary scalar (bytes are stored base64). |
| Concurrency rule | `python-library.md`, "read_only" | one writer per store; `connect(path, read_only=True)` opens a frozen view beside a writer; `relate serve --read-only` likewise. The server is the only writer of its store (plan question 5). |

## The decision model

TypeSafe. The current resolver is `src/aip/client/resolver.py` (`typesafe_sdk`: `TypeSafeClient`,
`Noul`, `Choice`, `Score`; dependency `typesafe-sdk>=0.7.1` in `pyproject.toml`). Answer shapes the
language expects are spec 2.4; the mapping from the SDK's `NoulAnswer`, `ChoiceAnswer`,
`ScoreAnswer` is: `value`, `confidence` (`|2·noul−1|` for noul, the SDK's own for the others),
`probabilities`, and `score` for a score question. Docs: https://docs.typesafe.ai/ (returned 308
to its new home on 2026-11-09; follow the redirect). The key lives in `aip config`, never in the
repo. Tests use the scripted resolver, so no key is needed for any proof before D1.

## Agent frameworks (track D2)

Each is reached over MCP (`aip mcp`, stdio). Use each framework's own MCP client; their docs are
public and move fast, so read them at D2 time: Google ADK (`google-adk`, MCPToolset), LangGraph
(`langchain-mcp-adapters`), Microsoft Agent Framework (`agent-framework`, MCP tools), Strands
(`strands-agents`, MCP client). Claude Code and Codex CLI take an MCP server from their config
files.

## Process

- Plan: https://github.com/zach-blumenfeld/aip-dev/issues/1. Tick, comment, commit, push to `dev`.
- Public plan issues for context on how 0.7 and 0.8 were run: `gh issue view 18 -R
  zach-blumenfeld/aip` and `19` (19 is superseded by this plan; do not edit it).
- Zach's constraints that are not in code: the design conversation stays in his `~/Documents` and
  never enters a repo; keyword lists are maintained only in the spec's glossary; the console repo
  stays separate from `aip`.
