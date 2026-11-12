# The Studio

The Studio is the console's page for a person who does not code: they describe a procedure, answer
what the documents leave open, adjust the wording and the numbers, and save it. It was a card
canvas with editing at C2; C4 (2026-11-10) replaced it with what is described here, because a canvas
of cards is still a program to someone who has never written one.

## One page, three things

```
┌ crumbs, name and description, status, Undo, Save draft, Publish, Source, Settings ┐
├──────────── chat ────────────┬──────────────── the step graph ─────────────────────┤
│ you: the brief               │  control or data flow, down or right                │
│   ✓ read the documents       │  click a node: its form opens under the graph       │
│     reading refund-policy.md │                                                     │
│ [Your turn: the questions]   │  a node with errors, or one that needs a script,    │
│   ✓ wrote the procedure      │  carries a note                                     │
│ review · diff                │                                                     │
│ [message box]  add documents │                                                     │
└──────────────────────────────┴─────────────────────────────────────────────────────┘
  diagnostics · Source (procedure.aip in the grammar's colours)
```

## The chat runs procedures

The Studio has no conversation of its own: every message runs a procedure that ships with aip ahead,
with a chat model answering its `Task_Agent` steps (`aip runah`, aip's `docs/runah.md`).

- **The first message on a new procedure is a brief.** It runs `aip runah build_procedure --human
  ask_user` with `brief` (the message), `documents` (the draft's `assets/docs/`, where documents
  dropped on the pane are saved, or nothing), `out` (the draft's folder, a placeholder,
  `new_procedure`, until the procedure has a name) and `title` (the name field of the brief box, or
  empty). With no name given, the model names the procedure in `draft` after the brief's subject,
  what the procedure handles, not the brief's first words; when the run is done the console's
  process renames the folder to the `procedure` its result names (Undo puts the old folder back).
  `--human ask_user` leaves the questions to the person: the run stops there, the pane shows the
  questions as a form, and the answers go back through `aip runah <run id> --answers`, which puts
  them into the pause and runs on. The run then writes the folder, compiles it until it compiles,
  tries one run that runs none of the scripts the model wrote, and reviews it against the rules,
  ending with a `Scripts:` section that says what each script touches outside the working directory.
- **Every later message is an instruction.** It runs `aip runah edit_procedure` on the draft's folder
  with the instruction and the same documents.
- **What the pane shows.** Each `--progress` line in plain words: a step ("wrote the procedure",
  "compiled it") and each tool call of the model ("reading refund-policy.md", "writing
  procedure.aip", "compiling"); `src/studio/chat.ts` holds the words. When a run ends, the review
  (`build_procedure`) or what changed (`edit_procedure`), the diff of `procedure.aip` and the files
  it wrote. A run the model could not finish says why; a pause the model gave up on is a form like a
  human step's.
- **Undo, one per run.** The console's process copies the draft's folder aside before each run
  (outside the run's working directory, so the model never sees it); Undo puts the last copy back.
  A form's edit is undone the same way, one at a time, newest first.
- **The record.** The runs are recorded as agent `studio` in the tab's session; each task the model
  answered is `answered_by: {agent: "runah", model: <the id the endpoint reported>}`, marked
  `observed`, with its tool calls and tokens, so History shows what the model did and what it cost.

## The graph and the forms

The graph is the procedure page's step graph (`src/graph/`, `views/StepGraph.tsx`), drawn again after
every run and every edit from the compiler's graph. The forms (`views/StudioForm.tsx`) edit what a
person changes by hand:

| On | Fields |
|---|---|
| a step | what it does (its description); where each way out leads, among the steps of its block, `end` or the next pass |
| a `Task_Agent` | its prompt file, when it has one |
| a `Decide` | each question's wording, and the labels of a `choice` or `score` |
| a step that produces an answer with labels | the labels |
| a `Route` | the confidence bar of its `Confidence_Below` |
| a loop | its cap, its `Until`, and whether reaching the cap first fails the run or carries on |
| the procedure | its name and description, above the graph |

Each field is a text edit of `procedure.aip` at the span `aip compile --json` gave the node or the
edge (`src/studio/edit.ts`), applied by the page, then formatted (`aip fmt --stdin`) and compiled
(`aip compile --check --json --partial --stdin`) by the console's process against the draft's folder
before the graph is drawn again. The compiler is the only rule book: a change it refuses shows its
diagnostics, on the node and in the list, and the draft cannot be saved until it is undone or fixed.
A label renamed in its place (the same position in the list, a new word) is renamed on the branches
of the routes that read the answer and on a question's criteria; a label added or taken away is
the compiler's to report. Anything structural, a new step, a loop, a rewire, is asked of the chat.

## The boundary, shown

A person who does not code cannot write a script. A step whose `Run_Script` names a file the draft
does not have (the compiler's `missing_file`) carries "needs a script" on the graph and its form
says to ask a developer; the draft does not compile until the file is there. `build_procedure`'s
review says the same of a stub it wrote, and the pane shows the review.

A script the model wrote is code nobody has read yet, and it runs on the machine that runs the
procedure. The page keeps the paths of the scripts each run added or changed (`scriptsWritten` in
`src/studio/chat.ts`) and, while the draft has them, shows them under "scripts the model wrote, read
before you run or publish", each with its text. The first Save draft or Publish of such a draft asks
once that they were read ("I have read them" or "Not yet"); it asks again only when a later run
changes them. `build_procedure`'s trial runs none of them, and its review's `Scripts:` section says
what each touches outside the working directory.

## Run

A saved draft runs for real from the Studio (plan C5). **Run** sits beside Save draft and comes on
once the save has returned the draft's `bundle_id`; any edit after that turns it off until the next
save, so what runs is what the server holds. Saving keeps the bundle as an `.rl` in the console's
process (`aip compile -o`, the same id), and Run opens the run console on it, `#/run/bundle:<id>?from=studio`,
in a tab of its own, so the Studio stays as it is. The process runs that file, so the run is recorded
against the draft.

The run console asks how to run. **Run ahead** (`aip runah`, the default from the Studio) has runah's
model answer the tasks and stops at the steps ticked as **human steps** (`--human`); the picker lists
the procedure's `Task_Agent` steps and ticks the ones written for a person: a prompt that begins with
the drafter's marker, "This is a task for a person, not for you" (build_procedure's `draft` and
edit_procedure's `rewrite` write it), or a description that says a person does it. The rule is
aip's (`aip.model.answerer.human_steps`, the steps `aip runah` stops at with no `--human`, since R8);
the page ticks what the description's `human_steps` names (`src/run/human.ts`). **Run** (`aip run`) pauses at every task instead. The Start step's inputs are a
form, typed from `aip info --json`.

A pause is answered through a form built from the step's `Produce` fields: a `true_or_false` is two
buttons, a string a text box, a choice or a score its labels, and a `list` whose rows the task carries
(the one list in the state it reads, as `make_procedure`'s `approve` reads `folders`) a checklist.
The answer as hand-typed JSON stays behind the form. The person's answers go back through `aip runah
<run id> --answers`, which runs on to the next human step or the end.

The scripts gate, once more: the scripts the model wrote execute at this moment, so the first Run of
a draft that has them asks again that they were read, naming each with what the chat's review said it
touches. A later Run asks only if they changed.

Runs started this way are recorded as agent `studio` in the page's session, and show in History and on
the procedure's page like any other. The record says which answers were the person's (answered by
`studio`) and which runah's (`runah`, with the model the endpoint reported); the run console shows the
run's working directory.

## Settings

The model `aip runah` runs the chat with (endpoint, key, model name, with a line per provider:
Anthropic, OpenAI, Gemini, Ollama), written with `aip config runah --model-uri/--model-name/
--model-key`, and the decision model, written with `aip config`, both through the console's process
(`POST /console/settings`). A key is never sent back to the page, only whether one is set. A model
the environment sets (`AIP_RUNAH_MODEL_URI`, `AIP_RUNAH_MODEL_NAME`, `AIP_RUNAH_MODEL_KEY`) says so,
since the environment wins over the file. With no key for it the chat is closed and says why; the
graph and the forms still work.

## Where things are

| | |
|---|---|
| `bin/aip-console.mjs` | the Studio's workspaces (a working directory per open Studio, the draft's folder in it, the copies Undo puts back) and its endpoints: `studio/open`, `check`, `read`, `documents`, `build`, `edit`, `undo`, `save` (which keeps the saved bundle for Run), and `settings`; `runah`, the run console's run ahead |
| `src/views/Studio.tsx` | the page: opening, checks, Undo, save and publish, Run and its scripts gate, the graph, Source, Settings |
| `src/views/Run.tsx` | the run console: run or run ahead, the human-step picker, the pause forms |
| `src/run/human.ts` | the Task_Agent steps of a graph, and which are a person's |
| `src/views/StudioChat.tsx` | the chat: a turn per message, the stream of a run, the human form, the review and the diff |
| `src/views/StudioForm.tsx` | the form of the node picked on the graph |
| `src/studio/edit.ts` | the field edits as text edits at spans |
| `src/studio/chat.ts` | the chat's words, a human step's questions, the scripts a draft lacks, the scripts a run wrote, what the reviews say each touches |
| `e2e/agent.mjs` | the stand-in chat model the e2e suite runs `aip runah` against; `e2e/studio-run.spec.ts` runs a draft from the Studio |

## A seam for another backend

The page asks the console's process to run a message (`studio/build`, `studio/edit`), relays its
lines, answers a human step (`resume` with `studio: true` and the workspace) and reads the folder when
it stops. That is the whole interface; the process implements it with the `aip` CLI and `aip runah`. A
backend that drives the same procedures with another agent (Claude Code, say) implements those
endpoints and nothing in the page changes.
