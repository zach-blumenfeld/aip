# Studio

The Studio tab (`#/studio`) builds an AIP procedure in the browser and exports it as a skill zip: `SKILL.md`
plus a placeholder for every script and template the steps name. A coding agent can then write those files
for you in place, and the Studio checks its work before you accept it.

It works in both console modes (`--server` or a skill folder). Drafts are kept in this browser's local
storage.

## Examples

Two example designs are in [`examples/studio/`](../examples/studio):

| Example | What it shows |
|---|---|
| `expense-review` | A complete design with no files yet. The tutorial below takes it from import to a finished skill. |
| `meeting-notes` | A design with gaps: no `purpose`, a script with no outputs, a step reading a key nothing produces, no `requires`. Use it to learn [the lint panel](#the-lint-panel). |

## Tutorial: expense-review, start to finish

This builds a skill that checks a receipt against a travel policy, then approves it or explains why not. You
design the steps; a coding agent writes the scripts. You need `aip-spec`, `python` and a coding agent on this
machine (see [Complete with an agent](#complete-with-an-agent)).

### 1. Import the design

The Studio imports zips, so zip the folder first:

```
cd examples/studio
zip -r expense-review.zip expense-review
```

Open `#/studio`, click **Import a skill zip…** and pick `expense-review.zip`. It opens as a new draft.

### 2. Read the graph

```
extract → check-policy → by-policy ─ true  → approve ─┐
                                   └ false → explain ─┴→ end
```

| Step | Kind | What it does |
|---|---|---|
| `extract` | execution | A script reads `receipt_text` and outputs `amount`, `vendor`, `category`. |
| `check-policy` | decision | Answers one yes/no question, `within_policy`. |
| `by-policy` | router | Branches on `within_policy`. |
| `approve` | execution | A script reads `assets/limits.json` and outputs `approval_id`. |
| `explain` | client_task | The agent running the skill writes `explanation` from the template `assets/explain.md`. |
| `end` | end | Returns `vendor` and `amount`. |

Tick **data flow** to see which keys travel along each edge.

### 3. Look at what's unfinished

The lint panel shows no errors, only unfinished items: `check-policy`, `approve` and `explain` have no
description, and the `within_policy` question has no instructions. Leave them: the agent fills empty prose.

If you change the design now, for example adding an output, keep the lint panel free of errors. The agent
can't start while there are errors.

### 4. Hand it to the agent

1. Click **Complete with an agent…**, then **Start**. The Studio writes the scaffold to
   `<workdir>/studio/expense-review/`: `SKILL.md`, stubs for `scripts/extract.py` and `scripts/approve.py`,
   and placeholders for `assets/limits.json` and `assets/explain.md`.
2. Click **Copy prompt** and paste it into your coding agent, started anywhere. The prompt holds the folder
   path, your design, and the rules for what the agent may change.
3. Leave the Studio open. It counts the files as they're written: `Waiting for the agent: 2 of 4 placeholder
   files written.`

### 5. Read the checks

Each time the folder stops changing, the Studio runs four checks (validate, adherence, contract,
completeness; see [The checks](#the-checks)). A check can fail while the agent is still writing. It runs
again on the next change.

When a check fails, its failures name the step or file, for example:

```
step `approve` (`scripts/approve.py`): does not print the declared output `approval_id`
```

Paste them into the agent.

When every check passes, the panel says **Every check passed**. Before you accept, read:

- **Prose the agent wrote**: every empty field it filled. Edit them later in the Studio if the wording is wrong.
- **The diff** against the scaffold: the checks prove each script runs and returns the right keys and types,
  not that `extract.py` parses receipts well. That's for you to judge.

### 6. Accept and ship

Click **Accept**. The agent's prose goes into the draft and its files replace the placeholders. Nothing is
left unfinished.

**Export scaffold…** → **Download `expense-review.zip`** gives you the finished skill. With a server,
**Publish to catalog** publishes it, and the run page can run it.

## Ways to start a draft

- **new draft** in the drafts bar, or **New in Studio** on the catalog page: a blank draft.
- **Import a skill zip…**: any skill zip, valid or not. Files the steps don't name are kept and exported as
  they are.
- **Import from catalog** (with a server), or **edit in Studio** on a procedure page: a published revision.
  On export, your edits are written into the original `SKILL.md`, so an unedited line comes back unchanged.

A skill written in an older format shows a banner with aip-spec's upgrade note. The export always writes
format `0.6a1`.

## Build the graph

The graph is on the left and the editor panel on the right. Click a step to edit it. Click
**procedure settings** to edit the skill as a whole.

- **First step**: an empty draft offers only runnable kinds (decision, execution, client_task), because the
  first step is the start.
- **Add a step after this one**: inserts the new step between this step and its next one, so the chain stays
  connected.
- **Routers**: each branch row has a value, a target, and **+ kind** buttons that create a new step on that
  branch. **fill from the decision before** fills in the rows from the feeding question's answers (`true`/`false`
  for a yes/no question, the labels for a choice).
- **delete step**: the step before it is re-linked to the step after it, when there is exactly one.
- **make this the start**: moves a runnable step to the front.
- **data flow**: draws which keys travel along each edge. **left to right** turns the graph sideways.

Edges are fields (`next step`, router branches), so a step can never have two outbound edges.

### Procedure settings

`name` (kebab-case; it becomes the zip's folder), `description`, `purpose`, `trigger_when`,
`do_not_use_when`, `anti_patterns`, and `requires`. Tick **scripts need an interpreter** for
`python 3.10`, then add packages and tools.

### Step fields

| Kind | Fields |
|---|---|
| decision | questions (`noul` yes/no, `choice`, `score`), instructions, criteria, an optional review threshold per question, `history` |
| execution | `script` (under `scripts/`), command (default `python` only), `assets`, `timeout` |
| client_task | `template` (under `assets/`), `assets`, `references` (path and when to load it), `framing` |
| router | `branch_on`, branches |
| end | inputs: the procedure's result |

### Inputs and outputs

Each row is a name, a type (`string`, `integer`, `float`, `boolean`, `object`, `list[*]`) and an optional
description.

- **The start step's inputs** are what the client supplies.
- **add a key from the state…** lists the keys that reach this step on every path, with their types. Picking
  one gives you the right name and type.
- **Typing a new name** is allowed. The lint panel then reports `unproduced_input`, with two fixes: **declare
  as start input**, or **make it an output of…** an earlier step.
- **A decision's outputs** are read-only: one key per question (yes/no → boolean, choice → string,
  score → integer).

## The lint panel

Lint runs on every edit. Issues come in three tiers:

- **error**: aip-spec would reject the skill.
- **unfinished**: an empty field or a placeholder file. That's fine in a template.
- **warning**: advice.

Click an issue to jump to its field. Some issues have a fix button (for example, add `requires`). Each
step on the graph shows a marker for its worst issue. Every rule is listed in
[studio-lint.md](studio-lint.md).

Keys: **F8** / **Shift+F8** step through the issues. Outside a text field, **Delete** removes the selected
step, **Cmd/Ctrl+Z** undoes and **Shift+Cmd/Ctrl+Z** redoes.

To practise, import `meeting-notes`, then:

1. Click the `missing_requires` fix button.
2. Give `clean` an output named `clean_transcript` (string).
3. Write a `purpose`.

The errors clear.

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

- `aip-spec` on the PATH: `uv tool install git+https://github.com/zach-blumenfeld/aip-spec.git@v0.6a1`, or
  pass `--aip-spec PATH`.
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
