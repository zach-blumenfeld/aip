# Studio tutorial

Two example designs for the console's Studio tab. Commands run from the repo root.

## The examples

| Example | What it shows |
|---|---|
| `expense-review` | A complete design with no files yet. [The tutorial](#expense-review-start-to-finish) takes it from import to a finished skill. |
| `meeting-notes` | A design with gaps: no `purpose`, a script with no outputs, a step reading a key nothing produces, no `requires`. Use it to [practise the lint panel](#practise-the-lint-panel-meeting-notes). |

## expense-review, start to finish

This builds a skill that checks a receipt against a travel policy, then approves it or explains why not. You
design the steps; a coding agent writes the scripts. You need `aip-spec`, `python` and a coding agent on this
machine (see [Complete with an agent](../../docs/studio.md#complete-with-an-agent)).

### 1. Import the design

The Studio imports zips, so zip the folder first:

```
cd examples/studio
zip -r expense-review.zip expense-review
```

Open `#/studio`, click **Import a skill zip…** and pick `expense-review.zip`. It opens as a new draft.

### 2. Read the graph

```
start → extract → check-policy → by-policy ─ true  → approve ─┐
                                           └ false → explain ─┴→ end
```

| Step | Kind | What it does |
|---|---|---|
| `start` | start | Holds the procedure's one input, `receipt_text`, and hands the run to `extract`. |
| `extract` | execution | A script reads `receipt_text` and outputs `amount`, `vendor`, `category`. |
| `check-policy` | decision | Answers one yes/no question, `within_policy`. It has `fallback: true` so the finished skill runs without a decision model (the comment in the YAML says so). |
| `by-policy` | router | Branches on `within_policy`. |
| `approve` | execution | A script reads `assets/limits.json` and outputs `approval_id`. |
| `explain` | client_task | The agent running the skill writes `explanation` from the template `assets/explain.md`. |
| `end` | end | Returns `vendor` and `amount`. |

Tick **data flow** to see which keys travel along each edge.

### 3. Look at what's unfinished

The lint panel shows no errors, only unfinished items: `check-policy`, `approve` and `explain` have no
description, and the `within_policy` question has no instructions. Leave them: the agent fills empty prose.

There is one warning, `unmeasured_route` on `by-policy`: with `fallback: true`, the agent running the skill may
answer `within_policy` by hand, and nothing records how sure it was. That is the price of running without a
decision model. To measure the route instead, untick **fallback** on `check-policy`, tick `within_policy` under
**confidence**, and give `by-policy` a confidence check on `within_policy_confidence`.

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
completeness; see [The checks](../../docs/studio.md#the-checks)). A check can fail while the agent is still writing. It runs
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

## Practise the lint panel: meeting-notes

Zip and import it the same way:

```
cd examples/studio
zip -r meeting-notes.zip meeting-notes
```

The lint panel lists its errors. Then:

1. Click the `missing_requires` fix button.
2. Give `clean` an output named `clean_transcript` (string).
3. Write a `purpose`.

The errors clear.

Every rule is listed in [studio-lint.md](../../docs/studio-lint.md). For every Studio feature, see
[docs/studio.md](../../docs/studio.md).
