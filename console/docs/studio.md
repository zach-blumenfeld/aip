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

The Studio has no conversation of its own: every message runs a procedure that ships with aip, with
the agent model answering its `Task_Agent` steps (`--answer-with model`, aip's `docs/answerer.md`).

- **The first message on a new procedure is a brief.** It runs `build_procedure` with `brief` (the
  message), `documents` (the draft's `assets/docs/`, where documents dropped on the pane are saved,
  or nothing) and `out` (the draft's folder, named from the first words of the brief that say
  something: the folder's name is the procedure's). `--human ask_user` leaves the questions to the
  person: the run stops there, the pane shows the questions as a form, and the answers go back
  through `aip resume --answer-with model`. The run then writes the folder, compiles it until it
  compiles, tries one run, and reviews it against the rules.
- **Every later message is an instruction.** It runs `edit_procedure` on the draft's folder with the
  instruction and the same documents.
- **What the pane shows.** Each `--progress` line in plain words: a step ("wrote the procedure",
  "compiled it") and each tool call of the model ("reading refund-policy.md", "writing
  procedure.aip", "compiling"); `src/studio/chat.ts` holds the words. When a run ends, the review
  (`build_procedure`) or what changed (`edit_procedure`), the diff of `procedure.aip` and the files
  it wrote. A run the model could not finish says why; a pause the model gave up on is a form like a
  human step's.
- **Undo, one per run.** The console's process copies the draft's folder aside before each run
  (outside the run's working directory, so the model never sees it); Undo puts the last copy back.
  A form's edit is undone the same way, one at a time, newest first.
- **The record.** The runs are recorded as agent `studio` in the tab's session, the model's tool
  calls and tokens with each task, so History shows what the model did and what it cost.

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

## Settings

The agent model (endpoint, key, model name, with a line per provider: Anthropic, OpenAI, Gemini,
Ollama) and the decision model, written to `aip config` through the console's process
(`POST /console/settings`). A key is never sent back to the page, only whether one is set. A
model the environment sets (`AIP_AGENT_MODEL_KEY` ...) says so, since the environment wins over the
file. With no agent model key the chat is closed and says why; the graph and the forms still work.

## Where things are

| | |
|---|---|
| `bin/aip-console.mjs` | the Studio's workspaces (a working directory per open Studio, the draft's folder in it, the copies Undo puts back) and its endpoints: `studio/open`, `check`, `read`, `documents`, `build`, `edit`, `undo`, `save`, and `settings` |
| `src/views/Studio.tsx` | the page: opening, checks, Undo, save and publish, the graph, Source, Settings |
| `src/views/StudioChat.tsx` | the chat: a turn per message, the stream of a run, the human form, the review and the diff |
| `src/views/StudioForm.tsx` | the form of the node picked on the graph |
| `src/studio/edit.ts` | the field edits as text edits at spans |
| `src/studio/chat.ts` | the chat's words, a human step's questions, the scripts a draft lacks, a name from a brief |
| `e2e/agent.mjs` | the stand-in agent model the e2e suite runs the chat against |

## A seam for another backend

The page asks the console's process to run a message (`studio/build`, `studio/edit`), relays its
lines, answers a human step (`resume` with `studio: true`) and reads the folder when it stops. That
is the whole interface; the process implements it with the `aip` CLI and `--answer-with model`. A
backend that drives the same procedures with another agent (Claude Code, say) implements those
endpoints and nothing in the page changes.
