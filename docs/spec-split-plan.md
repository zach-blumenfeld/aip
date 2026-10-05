# Plan: split the spec out of the runtime

AIP is two things, and today they share one repo. The **spec** is the format: the pydantic
models, the validator, the runtime block every skill carries, and the authoring skill that
compiles source material into it. The **protocol** is the runtime: `Procedure.run`, the
client, the server, the backends, and the inspector. Spec users need a skill and two
pure-Python dependencies. Protocol users need a package and a server. This plan moves the
spec to `https://github.com/zach-blumenfeld/aip-spec` and makes `aip` depend on it.

Why the split is cheap: `src/aip/spec/models.py`, `skill.py`, `runtime.md`, and
`runtime-0.4a0.md` import only pydantic and pyyaml. The one spec module that reaches into
the runtime is `loader.py`, which builds the executable `Procedure`, and it stays here.

The install story follows [knowledge-index](https://github.com/zach-blumenfeld/knowledge-index):
one `curl | bash` line installs uv and the package with `uv tool install`, then
`<cli> skill install` drops the skill bundled in the wheel into every detected agent's
config directory. Its `src/ki/commands/skill.py` has the agent detection and can be lifted.

## How to use this plan

For an agent told "implement the next unchecked milestone in `docs/spec-split-plan.md`,
run the tests, tick it off, commit", starting from a fresh session with no history:

- Two checkouts, side by side: this repo at `~/dev/aip` on branch `aip-0.5a0`, and
  `aip-spec` at `~/dev/aip-spec` on `main`. If `../aip-spec` is missing, clone it:
  `git clone git@github.com:zach-blumenfeld/aip-spec.git ../aip-spec`. The GitHub repo is
  empty until S0 makes its first commit. The `tool.uv.sources` path in S1 assumes this layout.
- Milestones are ordered. S0 happens in `aip-spec`; S1 to S3 happen here. Each ends with a
  proof; run it and report what it printed.
- Read the files a milestone names before coding. The current code is the reference:
  `src/aip/spec/` for what moves, `tests/test_spec.py` for what the tests check,
  `skills/aip-runtime/` and `aip runtime --skill` for how a bundled skill is written out
  today, and knowledge-index's `src/ki/commands/skill.py` (a sibling checkout at
  `~/dev/knowledge-index`, or GitHub) for agent detection.
- Tests: `uv sync --group dev && uv run pytest -q` in whichever repo you changed. Keep
  both suites green; the counts in each proof are the target.
- Each milestone is one commit per repo touched (or a few, each green). Ticking off
  means changing `- [ ]` to `- [x]` on the heading in this file and adding one line under
  it: `Done <date>, commit <short sha>: <one-sentence note>`, naming the sha in each repo
  when both changed. This file lives in `aip`, so S0 ends with a commit in `aip-spec` and a
  tick-off commit here. End commit messages with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Do not push, do not tag, and do not start the next milestone in the same session. Stop
  after the commit and report the proof output. Zach reads the diff before anything moves.
- The `aip-skillbench` harness pins `v0.4a0` and is not touched. The section at the end
  says what it does once it re-bootstraps.

## What goes where

| Today in `aip` | After | Why |
|---|---|---|
| `SKILL.md`, `references/skill-creation-best-practices.md` | `aip-spec` root, and bundled into its wheel | the authoring skill; the repo root renders on GitHub and clones as a skill, the wheel copy is what `aip-spec skill install` writes |
| `assets/procedure.schema.json` | `aip-spec/assets/`, bundled | generated from the models; `SCHEMA_ID` points at the spec repo's tag |
| `scripts/validate.py` | `aip-spec/scripts/` | the plain-clone validator; it finds the sibling `src/` as now, and falls back to the installed package as now |
| `src/aip/spec/models.py`, `skill.py`, `runtime.md`, `runtime-0.4a0.md` | `aip-spec/src/aip_spec/` | the format, with no runtime import |
| `src/aip/spec/loader.py` | stays, in `src/aip/spec/` | builds `aip.model.Procedure`; that is protocol |
| `src/aip/spec/aip-runtime/SKILL.md`, `runtime_skill_text()` | stay, move to `src/aip/client/` | the `aip-runtime` skill is about the client |
| `examples/billing-support` | `aip-spec` only, bundled as package data | it documents the format; `aip` installs `aip-spec` and reads the example from it, so nothing is duplicated |
| `tests/test_spec.py` | split: models, schema, graph, folder, and CLI-contract tests go to `aip-spec`; `LoaderEndToEnd` stays as `tests/test_loader.py` | tests follow the code |
| `skills/aip-runtime/` | stays | protocol |
| `README.md` §Install, §Procedures, §Specification, the version-bump checklist | rewritten | `aip` installs as a package; the skill comes from `aip-spec` |

The package in `aip-spec` is `aip_spec`, a distribution named `aip-spec` whose version is
the format version. Sharing the `aip.*` namespace across two distributions is possible but
brittle, so it is not done. Here, `aip.spec` remains as the home of the loader and
re-exports the format from `aip_spec`, so the five modules that import `aip.spec` today do
not change.

## - [x] S0 — Create `aip-spec`

Done 2026-10-05, commit 94215a9 in `aip-spec`: the spec half (models, validator, runtime block, authoring skill, example) as the `aip-spec` distribution with its CLI, installer, and 36 tests; `SKILL.md` also drops `scripts/validate.py` from anti-pattern 3 in favour of `aip-spec validate`, since the installed skill no longer carries the script.

In the new repo, from the current `aip-0.5a0` tree.

- Root: `SKILL.md`, `references/`, `assets/procedure.schema.json`, `scripts/validate.py`,
  `examples/billing-support/`, `README.md`, `CHANGELOG.md` (the format entries lifted from
  here), `LICENSE`, `install.sh`.
- `pyproject.toml`: `name = "aip-spec"`, `version = "0.5a0"`, `dependencies = ["pydantic>=2.11", "pyyaml>=6.0.3"]`,
  `dev = ["pytest>=8"]`, hatchling, `packages = ["src/aip_spec"]`, and a console script
  `aip-spec = "aip_spec.cli:main"`. A `force-include` maps the root `SKILL.md`, `references/`,
  and `assets/` into `aip_spec/_skill/` and `examples/` into `aip_spec/examples/`, the way
  knowledge-index bundles `skills/knowledge-base/`. One file on disk, no copies to keep in sync.
- `src/aip_spec/`: `models.py`, `skill.py`, `runtime.md`, `runtime-0.4a0.md`, an
  `__init__.py` exporting what `aip.spec.__init__` exports today minus `runtime_skill_text`,
  plus `skill_dir()` and `example_dir(name)` returning the bundled paths.
- `aip_spec.cli`: `validate <folder>` (today's output contract), `schema [--write]`,
  `runtime` (prints the block), `skill install [agent] [--path DIR]`, `skill list`,
  `skill remove`, `example <name> --out DIR`. `scripts/validate.py` wraps `validate`.
- `SPEC_URL` and `SCHEMA_ID` in `models.py` point at `https://github.com/zach-blumenfeld/aip-spec`
  and `https://raw.githubusercontent.com/zach-blumenfeld/aip-spec/v0.5a0/assets/procedure.schema.json`.
- `install.sh`: install uv if missing, `uv tool install --force git+https://github.com/zach-blumenfeld/aip-spec.git@v0.5a0`,
  then `aip-spec skill install`, non-fatal when no agent is detected. Idempotent.
- `tests/test_spec.py`: everything but `LoaderEndToEnd` and the `FakeJev` it uses; the
  CLI-contract test calls `aip_spec.cli`. The runtime-block drift test reads the root
  `SKILL.md`. A new test checks `skill install --path` writes a folder that passes
  `check_frontmatter` and carries `references/` and `assets/`.
- `SKILL.md` changes, and only these: the functional-test step says to run the skill with
  the `aip-runtime` skill if it is installed and otherwise to execute the procedure
  yourself per the runtime block, and names no `aip` command; the validator line becomes
  `aip-spec validate ./<skill-name>`, with `uv run scripts/validate.py` noted as the
  equivalent from a clone; the `compatibility` field names `uv`.

Proof:

```
uv sync --group dev && uv run pytest -q                       # the spec half of today's 128
uv run scripts/validate.py examples/billing-support           # VALID
uv run aip-spec schema | diff - assets/procedure.schema.json  # no output
uv run aip-spec skill install --path /tmp/skills && uv run aip-spec validate /tmp/skills/aip 2>&1 | head -1
    # the authoring skill is not an AIP skill, so this reports the body error; the point is the folder exists
    # with SKILL.md, references/, assets/, and `head -3 /tmp/skills/aip/SKILL.md` shows the frontmatter
```

## - [ ] S1 — `aip` depends on `aip-spec`

Here. The repo stops being a skill.

- `pyproject.toml`: add `aip-spec @ git+https://github.com/zach-blumenfeld/aip-spec.git@v0.5a0`
  to `dependencies`; drop `jsonschema` if nothing else uses it. Add
  `[tool.uv.sources] aip-spec = { path = "../aip-spec", editable = true }` under a comment
  saying it is for local work across both checkouts and the git pin is the published truth.
- `src/aip/spec/__init__.py` re-exports from `aip_spec`; `models.py`, `skill.py`, and the
  two `runtime*.md` are deleted. `loader.py` imports from `aip_spec`.
- `runtime_skill_text()` and `aip-runtime/SKILL.md` move to `src/aip/client/`; `aip runtime`
  and `tests/test_runtime_skill.py` follow.
- Delete `SKILL.md`, `references/`, `assets/`, `scripts/validate.py`, `examples/` from the root.
- `aip validate` and `aip schema` call `aip_spec`; `aip runtime` prints `aip_spec.runtime_text()`.
- Every test that defines `EXAMPLE` as a repo path (`test_spec`, `test_runner`,
  `tests/server/test_records.py`, and the fixtures in `tests/server/`) takes
  `aip_spec.example_dir("billing-support")` instead.
- `tests/test_spec.py` → `tests/test_loader.py` holding `LoaderEndToEnd`.
- `docs/running.md`'s worked example and `aip publish examples/billing-support` lines say
  where the folder comes from: `aip-spec example billing-support --out .`.
- `.gitattributes`, the `docs/PLAN.md` inventory rows for the skill and the example, and
  `docs/running.md` line 32 get the new paths.
- The inspector's `e2e/aip.ts` resolves `EXAMPLE` by running
  `uv run --project $AIP_REPO aip-spec example billing-support --out .aip-e2e/example`
  instead of joining a path. One line, in the other repo; note it here and do it there.

Proof:

```
uv sync --group dev && uv run pytest -q          # same count as before S1 minus the tests that moved
uv run aip validate "$(uv run python -c 'import aip_spec; print(aip_spec.example_dir("billing-support"))')"   # VALID
uv run aip runtime | head -1                     # "# AIP runtime — format 0.5a0"
ls SKILL.md references assets examples 2>&1 | grep -c "No such"   # 4
```

## - [ ] S2 — Install path

- `aip skill install [agent] [--path DIR]`, `skill list`, `skill remove`: drops both skills,
  `aip-runtime` from this package and the authoring skill through `aip_spec.skill_dir()`,
  into each detected agent, using the same detection as `aip-spec skill install`. (Share the
  code: `aip_spec` owns the agent-detection helper and `aip` calls it with two skill folders.)
  `aip runtime --skill --out` stays as the low-level write of one skill.
- `install.sh` at the root of this repo: install uv if missing,
  `uv tool install --force git+https://github.com/zach-blumenfeld/aip.git@<tag>` (which pulls
  `aip-spec` as a dependency), then `aip skill install`, non-fatal when no agent is
  detected. Idempotent. The URL in the README is the raw GitHub path to this file.
- `README.md`: §Install becomes

  ```
  curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash    # aip + aip-spec + both skills
  ```

  with "only the format, no runtime" pointing at the `aip-spec` one-liner, and "prefer
  Python tooling" giving `uv tool install`. The `git clone … .claude/skills/aip` instructions
  go away. §Procedures and §Specification link to the spec repo. "Why is the AIP SKILL.md
  not written in AIP?" moves to the spec repo.
- The version-bump checklist is rewritten as two ordered lists. In `aip-spec`:
  `FORMAT_VERSION` and `version`, `runtime.md` (keeping the old text as `runtime-<old>.md`
  and adding it to `LEGACY_VERSIONS`), the schema, `SKILL.md`, the example, the README, the
  CHANGELOG, `install.sh`'s tag, the tag. Then in `aip`: the git pin, the `aip-runtime`
  skill's `aip-version`, `install.sh`'s tag, the CHANGELOG. The spec is tagged first,
  always, because the pin names the tag.
- A test that `aip skill install --path` writes both folders and that each passes
  `check_frontmatter`.
- `CHANGELOG.md` `[Unreleased]` gets one line for the split and one for `aip skill install`.

Proof:

```
uv run pytest -q tests/test_runtime_skill.py
uv run aip skill install --path /tmp/skills && ls /tmp/skills      # aip  aip-runtime
```

## - [ ] S3 — Tag and pin

After Zach has read S0 to S2.

- Tag `v0.5a0` in `aip-spec`.
- Here, confirm the git pin resolves to that tag from a clean environment, with the
  `tool.uv.sources` path override absent, and that the installer runs end to end on a
  machine with no uv.

Proof:

```
cd "$(mktemp -d)" && bash <(curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/aip-0.5a0/install.sh) \
  && aip skill list && aip-spec validate "$(aip-spec example billing-support --out . && echo ./billing-support)"
```

## What `aip-skillbench` does after this

Its bootstrap clones `aip` into `.claude/skills/aip` and copies that into the authoring
workspace. After the split it installs the two packages and runs `aip skill install --path`
into the workspace, which is what the clone was standing in for. `_aip.py` reads
`FORMAT_VERSION` from the clone; that becomes `aip-spec --version` or an import. Nothing
changes until it re-bootstraps.

## Not in this plan

- Publishing either package to PyPI. The names `aip` and `aip-spec` are free as of
  2026-10-05; when it happens, `aip-spec` goes first, because PyPI refuses a package whose
  dependency is a git URL, and the two `install.sh` lines lose their `git+` prefix.
- A self-contained `scripts/validate.py` that needs neither a clone nor an install. PEP 723
  can declare `aip-spec` as a git dependency of the script; with `aip-spec skill install`
  as the front door it matters less, and it belongs to the spec repo once it exists.
- Moving the server design or this plan's parent, `PLAN.md`, which stay here.
