# Studio

The Studio tab (`#/studio`) builds an AIP procedure in the browser and exports it as a skill zip: `SKILL.md`
plus a placeholder for every script and template the steps name. A coding agent can then write those files
for you in place, and the Studio checks its work before you accept it.

It works in both console modes (`--server` or a skill folder). Drafts are kept in this browser's local
storage.

New here? Start with the [tutorial](../examples/studio/README.md): it takes an example design to a finished
skill, agent step included. The rest of this page is the reference.

## Ways to start a draft

- **new draft** in the drafts bar, or **New in Studio** on the catalog page: a blank draft.
- **Import a skill zip…**: any skill zip, valid or not. Files the steps don't name are kept and exported as
  they are.
- **Import from catalog** (with a server), or **edit in Studio** on a procedure page: a published revision.
  On export, your edits are written into the original `SKILL.md`, so an unedited line comes back unchanged.

A skill written in an older format shows a banner with aip-spec's upgrade note, which names `aip upgrade`; the
console's process can run it on the imported files (`POST /console/upgrade`). The export always writes format `0.8`.

## Build the graph

The graph is on the left and the editor panel on the right. Click a step to edit it. Click
**procedure settings** to edit the skill as a whole.

- **First step**: an empty draft offers the runnable kinds (decision, execution, client_task) for the first step
  that runs. Picking one adds the `start` step with it: the start holds the inputs the client supplies and
  names that step (`inputs_to`). A draft has exactly one start step; the export writes it first.
- **Add a step after this one**: inserts the new step between this step and its next one, so the chain stays
  connected. Works from the start step too.
- **Routers**: each branch row has a value, a target, and **+ kind** buttons that create a new step on that
  branch. **fill from the decision before** fills in the rows from the feeding question's answers (`true`/`false`
  for a yes/no question, the labels for a choice).
- **delete step**: the step before it is re-linked to the step after it, when there is exactly one. Deleting the
  start step leaves the draft without one; the lint panel's **add a start step** fix puts one back.
- **make this the first step**: the start step hands to this runnable step instead.
- **data flow**: draws which keys travel along each edge. **left to right** turns the graph sideways.

Edges are fields (`next step`, router branches), so a step can never have two outbound edges.

### Procedure settings

`name` (kebab-case; it becomes the zip's folder), `description`, `purpose`, `trigger_when`,
`do_not_use_when`, `anti_patterns`, and `requires`. Tick **scripts need an interpreter** for
`python 3.10`, then add packages and tools.

### Step fields

| Kind | Fields |
|---|---|
| start | inputs: what the client supplies; first step (`inputs_to`) |
| decision | questions (`noul` yes/no, `choice`, `score`), instructions, criteria; **confidence**: tick a question and the step also writes `<question>_confidence` to the state, the probability the decision model put on its answer; **fallback**: whether a client with no decision model may answer by hand (off by default; the help says what it costs); `history` |
| execution | `script` (under `scripts/`), command (default `python` only), `assets`, `timeout` |
| client_task | `template` (under `assets/`), `assets`, `references` (path and when to load it), `framing` |
| router | `branch_on`, branches; **confidence check**: a float key (a decision's `<question>_confidence`, or a declared float output), a bound in 0 to 1, and the step the run goes to when the key is below it, or absent or null. Checked before the branches; one check per router |
| end | inputs: the procedure's result |

A decision answered by hand records no confidence, so a router's check on it fires with reason `absent`. The
linter classifies what feeds each router as deterministic, measured or unmeasured and warns where an unmeasured
source routes the run ([studio-lint.md](studio-lint.md)); the procedure page shows the class the server stored
at publish.

### Inputs and outputs

Each row is a name, a type (`string`, `integer`, `float`, `boolean`, `object`, `list[*]`) and an optional
description.

- **The start step's inputs** are what the client supplies.
- **add a key from the state…** lists the keys that reach this step on every path, with their types. Picking
  one gives you the right name and type.
- **Typing a new name** is allowed. The lint panel then reports `unproduced_input`, with two fixes: **declare
  as start input**, or **make it an output of…** an earlier step.
- **A decision's outputs** are read-only: one key per question (yes/no → boolean, choice → string,
  score → integer), plus `<question>_confidence` (float) for each question ticked under **confidence**.
- **A key may have more than one producer.** The lint panel lists it as information (`duplicate_producer`):
  where a run passes through both, the later one overwrites the value. The data-flow view draws an arrow from each.

## The lint panel

Lint runs on every edit. Issues come in four tiers:

- **error**: aip-spec would reject the skill.
- **unfinished**: an empty field or a placeholder file. That's fine in a template.
- **warning**: aip-spec's warnings (a route an unmeasured source steers) and the Studio's advice.
- **info**: aip-spec's information (a key with several producers).

Click an issue to jump to its field. Some issues have a fix button (for example, add `requires`). Each
step on the graph shows a marker for its worst issue. Every rule is listed in
[studio-lint.md](studio-lint.md).

Keys: **F8** / **Shift+F8** step through the issues. Outside a text field, **Delete** removes the selected
step, **Cmd/Ctrl+Z** undoes and **Shift+Cmd/Ctrl+Z** redoes.

To practise, fix the `meeting-notes` example ([steps](../examples/studio/README.md#practise-the-lint-panel-meeting-notes)).

## Export

**Export scaffold…** shows the error, unfinished and warning counts, then:

- **Download `<name>.zip`**: never blocked. The zip holds:
  - `SKILL.md`
  - a working Python stub per execution step. It reads the stdin JSON and prints each declared output with a
    dummy value, so the scaffold runs end to end.
  - a template per client task, listing its inputs as `{key}`
  - a placeholder for each reference and asset
  - `source/README.md`, listing what's left to do, and `DRAFT: N errors remain` when there are errors
- **Publish to catalog** (with a server): disabled while there are errors, because the server would reject
  the skill.

Every placeholder holds the line `AIP-STUDIO-PLACEHOLDER`. It's unfinished until you replace the file's
content.

## Complete with an agent

The agent writes the placeholder files and fills the empty step descriptions, question instructions,
criteria text and `trigger_when` entries. It may not change the graph, names, types, file paths, `requires`
lists that already have entries, or anything you already wrote.

**You need**, on the machine running the console:

- `aip-spec` on the PATH: `uv tool install aip-spec`, or the aip installer
  (`curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash`), or pass
  `--aip-spec PATH`. The format lives at `packages/aip-spec` in the [aip repo](https://github.com/zach-blumenfeld/aip).
- `python` or `python3` on the PATH.
- A coding agent that can edit files and run commands (Claude Code, Codex, Gemini CLI, …).

### Steps

1. Click **Complete with an agent…**. If the design isn't ready, the panel lists why and **Start** is
   disabled. Click a reason to jump to its field. The agent needs:
   - `purpose`, `description` and at least one `trigger_when` entry
   - every input and output named
   - an output on every execution and client task step, and an input on the end step
   - no lint errors
   - only Python launchers
2. Click **Start**. The scaffold is written to `<workdir>/studio/<name>/`, and the panel shows the prompt with
   that path in it.
3. Click **Copy prompt** and paste it into your coding agent. The agent edits the folder in place.
4. Leave the Studio open. It shows how many placeholder files the agent has written so far, and checks the
   folder each time the files stop changing.
5. When every check passes, read the diff and click **Accept**. The filled fields go into your draft, and the
   agent's files replace the placeholders.

If a check fails, paste the failures into the agent. The Studio checks again when the folder changes. The
handoff survives a page reload. **start over** writes a fresh scaffold, and moves the old folder to
`<workdir>/studio/.previous/`. Nothing is deleted.

**Edit the instructions** changes the prompt's instructions for this draft. The folder path and the
description of your design are always added after them.

### The checks

| Check | Passes when |
|---|---|
| aip-spec validate | the real validator reports no errors. Without aip-spec the checks refuse to run. |
| Adherence to the design | `SKILL.md` matches your draft on everything frozen. Fields the agent filled are listed under **Prose the agent wrote**. Packages or tools it added to an empty `requires` list are flagged for you to look at. |
| Script and template contract | each script, run with sample inputs of the declared types (each script's outputs feed the next), exits 0 and prints exactly its declared outputs with the right types. Each template's `{fields}` are the step's inputs, `{assets[stem]}` or `{meta.name}`. |
| Completeness | no placeholder marker is left, no referenced file is empty or only comments, and nothing is unfinished |

Each failure names its step, field or file. The checks don't run the whole procedure (decisions need a
decision model, client tasks a client), and they don't judge whether a script does the right thing. Read
the diff for that.

## Drafts

The drafts bar picks, creates, renames and deletes drafts. **reset** empties the open one. Delete and reset
ask once more in the bar. If the browser blocks storage, a notice says so, and the draft lasts only until
the page closes. Export to keep it.
