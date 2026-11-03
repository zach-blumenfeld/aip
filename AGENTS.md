# AGENTS.md

Instructions for AI agents working **on** this repository. If you are an agent being asked to
*use* AIP, read the aip repo's `skills/aip-runtime/SKILL.md` (running a published procedure) or
`skills/aip-compile/SKILL.md` (compiling material into one) instead.

## What this repo is

The console for [AIP](https://github.com/zach-blumenfeld/aip): catalog, source and revision diff,
run console, history, governance, and the Studio that builds a procedure in the browser. It is one
npm package, `aip-console`, with a small Node launcher (`bin/aip-console.mjs`) that serves the
built page and runs procedures through the `aip` CLI on this machine; the aip server serves no UI.
The package installs two commands, `aip-console` and `aip-inspector` (the old name, kept one more
release). It has no runtime npm dependencies but `yaml`; everything else is a dev dependency.

The runtime and the format are Python packages in the aip repo (`agent-instruction-protocol` and
`aip-spec`, one uv workspace, one version). This repo never vendors them: the e2e harness runs the
sibling checkout (`AIP_REPO`, default `../aip`) behind `uv run`, and the launcher runs whatever
`aip` is on the PATH.

## Repo map

| Path | What's there |
|---|---|
| `bin/aip-console.mjs` | the launcher: argument parsing, `aip --version` and `MINIMUM_AIP`, the `/console/*` endpoints (run, resume, cancel, validate, probe, handoff), the static server; loopback only |
| `src/` | the page: React + Vite, hash-routed. `api/` the typed client and the console's own endpoints; `views/` the pages; `graph/` the hand-rolled step graph layout; `diff/` line diffs; `run/protocol.ts` the launcher's event-stream protocol; `zip.ts` the skill zip reader and writer (`fflate`); `studio/` the Studio's Draft model, SKILL.md round-trip (`serialize.ts`), linter (`lint.ts`), scaffold, import, the agent prompt and checks, and `runtime-0.8.ts`, the runtime block verbatim |
| `e2e/` | Playwright specs and the harness: `prepare.mjs` writes `.aip-e2e/`, `aip.ts` / `aip-spec.ts` run the sibling repo's CLIs, `global-setup.ts` publishes the fixtures; `playwright.config.ts` starts the aip server and two consoles |
| `docs/studio.md`, `docs/studio-lint.md` | the Studio reference and its lint codes |
| `docs/plans/` | the historical plans (`PLAN.md`, `STUDIO-PLAN.md`); current plans are GitHub issues on the aip repo |
| `examples/studio/` | the Studio tutorial and its example design |
| `CHANGELOG.md` | the console's changelog |
| `.github/workflows/release.yml` | the release workflow, below |

## Conventions

- **Node 20 or newer, npm.** `npm install` to set up; `npm run typecheck && npm run e2e` must pass
  before any commit. The e2e suite needs `uv`, the sibling aip repo at `AIP_REPO` (default
  `../aip`), and a browser (`npx playwright install chromium`, or `PLAYWRIGHT_CHANNEL=chrome`).
- **Keep dependencies few.** Add a library only when a milestone names the need; the graph layout
  and the diff are hand-rolled for that reason, and the zip reader is `fflate`, bundled by Vite.
- **Do not change behaviour in a release branch.** If a test must change for a path or a version
  string, say so in the commit; if it must change for a behaviour, stop and write it down in the
  plan issue.
- **Plans live in issues on the aip repo, not here.** The roadmap is
  [aip#20](https://github.com/zach-blumenfeld/aip/issues/20); each release has a plan issue whose
  Track C milestones are this repo's, each naming the command that proves it. A fresh agent
  implements one milestone per session: read the plan's "Context" and "Rules", then only the first
  unchecked milestone; run its proof, tick it, comment `Done <date>, commit <sha>: <one sentence>`,
  commit. Product-visible questions sit under "Open items" with a default; take the default and say so.
- **Never edit `../aip` from here.** Where the console and the format disagree, the format wins
  (`packages/aip-spec` in the aip repo); say so in the commit.

## Versioning

- **Package version** `X.Y.Z` in `package.json` (and `package-lock.json`, which `npm version X.Y.Z
  --no-git-tag-version` keeps in step), SemVer, pre-1.0 so breaking changes bump the minor. It tracks
  the runtime release the console targets: 0.7.0 targets aip 0.7.0.
- **`MINIMUM_AIP`** in `bin/aip-console.mjs` is the oldest `aip` the launcher accepts; it moves when
  the console starts to depend on something newer in the CLI's JSON contract or the server API.
- The console does not carry a format version. The runtime block it embeds
  (`src/studio/runtime-0.8.ts`) is compared byte for byte to the aip repo's
  `packages/aip-spec/src/aip_spec/runtime.md` by `e2e/studio-lint.spec.ts`; a format change in the
  aip repo fails that test until the console catches up.

## Releasing

Releases are cut by the **`.github/workflows/release.yml`** workflow, **triggered manually**
(Actions → *Release to npm* → Run workflow) by a maintainer **after the release PR is merged to
`main`**. The workflow reads the version from `package.json`, refuses if `package-lock.json`
disagrees or if the tag already exists, runs `npm ci && npm run build && npm pack`, checks the
tarball carries `bin/aip-console.mjs` and `dist/`, tags `vX.Y.Z`, **stages** `aip-console` on npm
with `npm stage publish --provenance` from the `release` GitHub environment, and cuts a GitHub
Release whose body is the matching `## [X.Y.Z]` section of `CHANGELOG.md`.

**Staged, then approved by a person.** A staged version is held by npm and not installable until
the maintainer approves it with 2FA: on npmjs.com, the package's *Staged Packages* tab → *Approve*,
or `npm stage approve <stage-id>` (the id is in the run's summary). That approval is the last step
of every release. The workflow authenticates with npm's trusted publishing (OIDC, no token): the
package page names this repository, `release.yml` and the `release` environment as its trusted
publisher, and `npm stage publish` is the one action a trusted publisher is always allowed, so no
publish permission and no `NPM_TOKEN` secret exist. 0.7.0 was published by hand from a laptop
before any of this existed.

Running it with `target: dry-run` is the rehearsal for a new or changed workflow: same checks,
same build, same tarball, then `npm stage publish --dry-run`, no tag and no GitHub Release. It can
be repeated at the same version. A failed run that already pushed the tag is re-run after deleting
the tag (`git push origin :refs/tags/vX.Y.Z`).

So an agent's job for a release is **prep only — never build, tag, stage, approve or publish by hand:**

1. **Set the version** with `npm version X.Y.Z --no-git-tag-version` (SemVer, pre-1.0 → breaking
   changes bump the minor; match the aip release the console targets), and move `MINIMUM_AIP` if the
   console now needs a newer `aip`.
2. **Finalize `CHANGELOG.md`**: roll `## [Unreleased]` into a single `## [X.Y.Z] — <date>`
   section (one section per release — the workflow extracts just that one). The `## [X.Y.Z]`
   heading format is **load-bearing** (awk-matched); leave a fresh empty `## [Unreleased]` above
   it.
3. Open the release PR. The maintainer merges it, triggers the workflow, and approves the staged
   version on npmjs.com.

Never move or force-push a published tag.

## When you're unsure

- For the server API the page calls, the aip repo's `docs/server-design.md` and
  `src/aip/server/app.py` are the shapes; `src/api/types.ts` here repeats them.
- For the CLI's JSON lines the launcher relays, the aip repo's `docs/cli-json.md`.
- For what a procedure may contain, the aip repo's `packages/aip-spec/docs/specification.md` is
  the prose and `models.py` there is the law; `src/studio/lint.ts` here ports its rules.
- For the Studio's behaviour, `docs/studio.md` here is the contract.
