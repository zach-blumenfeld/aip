# AIP language: specification

The text form of an AIP procedure: a small, readable file that a person can follow like a runbook, an agent can write one step at a time, and a compiler can check completely before anything runs. This document is the language on its own terms. How it lands in the AIP runtime, server and console is the AIP repository's business; see `AGENTS.md` for where the two meet.

Written 2026-11-03, revised 2026-11-09. Examples: `examples/language/`. What the language does not do yet: `docs/language/limitations.md`. Why it has no expressions, decided and not to be re-derived: `docs/language/no-expressions.md`. What running a bundle requires of a runtime: `docs/language/runtime.md`.

---

## Summary: what we are building and why

**The problem.** A procedure is a graph of typed steps: decisions, scripts, agent tasks, routes between them, loops over lists. A graph with named edges written in a data format is hard for people to read and hard for agents to write without mistakes: every edge is a name to get right, and nothing on the page says which step a line belongs to. Each thing the procedure can express adds more of that.

**The change.** A procedure becomes one text file, `procedure.aip`, that reads top to bottom:

```aip
Procedure ticket_triage
  "Classify a batch of support tickets, draft replies, escalate the uncertain ones."

  Requires python 3.10

classify_question = "What kind of ticket is this and how does the customer sound?"

Start "The batch of tickets and the policy every reply must follow." {
  tickets: list
  policy: string
  Next_Step each_ticket
}

For each_ticket Over tickets As ticket, At_Most 50, Collect reply Into replies {

  Decide classify classify_question {
    Read ticket
    Answer_Questions {
      billing: true_or_false "Is this a billing question?"
      tone: choice [calm, angry] "How does the customer sound?"
    }
    Produce classification
    Next_Step by_tone
  }

  Route by_tone "Calm customers get a drafted reply; angry or uncertain ones are escalated." {
    Read classification.tone
    Confidence_Below 0.6 -> escalate
    calm  -> draft
    angry -> escalate
  }

  Task_Agent draft "Write a reply that follows the policy." {
    Read ticket, policy
    Produce reply: string
    Next_Step check
  }

  Execute escalate "Open a ticket in the tier-2 queue." {
    Read ticket
    Run_Script scripts/escalate.py
    Produce reply: string, queue: string
    Continue
  }

  Execute check "Does the reply quote the policy correctly?" {
    Read reply, policy
    Run_Script scripts/policy_check.py
    Produce passed: true_or_false
    Next_Step revise
  }

  Loop revise Until passed, At_Most 3, Else_Fail {
    Task_Agent fix "Revise the reply so it quotes the policy correctly." {
      Read reply, policy
      Produce reply: string
      Again check
    }
    Continue
  }

  Next_Step summarize
}

Task_Agent summarize "Summarize the batch for the team lead." {
  Read replies
  Produce summary: string
  Next_Step end
}

End "Every ticket has a reply or an escalation, and the lead has a summary." {
  Read summary, replies
}
```

A governance reader can follow that: every step is a card that says what it is, what it reads, what it produces and where it goes next. An agent can write it one card at a time. A compiler can check it completely.

**Compiled, on purpose.** The compiler checks the procedure and produces one file, the **bundle**: the graph a runtime walks, plus every source file byte for byte, plus a hash. The bundle is the unit of publishing, running and auditing: the thing a reviewer approved is, provably, the thing that ran. Running a folder directly still works for development; it compiles in memory first, the way `go run` does. Nobody learns a build step to get started, and nothing unvalidated ever runs.

**The graph is the product.** A runtime walks the compiled graph in memory and never consults a database to pick the next step. The graph is also what a server projects into a graph database, so questions about procedures and runs are graph queries.

**State is written once, except in a loop.** A run carries one state: a set of named keys. Every key has exactly one producer on any path through the procedure. The only place a key takes a new value is inside a loop, where each pass may rewrite a key the loop carries, the way a fold threads an accumulator. There is nothing to declare: the compiler sees it from the reads and writes. What it rejects is the accidental overwrite, two unrelated steps writing the same key. What it gives authors is the one place a rewrite is correct, so a review loop is `Loop Until passed { fix }` instead of a `fixed_reply` key and a dead-end branch.

**Every condition in a procedure is on an answer.** A route branches on an answer, a loop's `Until` tests an answer, an aggregation combines answers. An answer is a value with, when a model gave it, a confidence and probabilities; nothing else in the state can be branched on. A script that wants to drive a route produces an answer type, and its answer has a value and no confidence, which is the truth about it. This is the principle that keeps every confidence check in the language honest: there is always one answer under it.

**A decision produces one key, and its answers carry their confidence.** `Decide triage` ends with `Produce triage_decision`: one key, whose fields are the questions. `triage_decision.tone` is a `choice` answer, an object holding the chosen label as `value`, the model's `confidence`, and the probabilities it put on every label; the same for `true_or_false` and `score`. There is no separate confidence key and nothing to opt into: a route that reads `triage_decision.tone` branches on its `value` and checks its `confidence`, and a hand-given answer has no confidence, so the check fires.

**What we are not doing.** We are not inventing a general programming language: seven step kinds, two loop forms, no expressions, no arithmetic, no function calls. Computation stays in scripts. We are not positioning this as "a language" to buyers: it is a structured text file, a step up from a markdown skill, that compiles to a bundle.

---

## 1. Decisions

| Decision | Choice | Why |
|---|---|---|
| Surface syntax (2026-11-03) | Our own, small, block-structured; not KDL, HCL, Python or any general language | Nothing popular fits a no-computation procedure language; general languages invite agents to write real code |
| Positioning (2026-11-03) | "A structured text file, a step up from markdown"; the word *language* is not used in product copy yet | Not to scare people off |
| Compiled or not (2026-11-03) | Compiled. The compiler is the validator with an output; running or publishing a folder compiles it on the fly | One artifact, one hash, one story; validation is kept as a property |
| Compiled form (2026-11-03, revised 2026-11-08) | A **bundle**: a Relate single-file graph database (`.rl`) holding the source, the files and the derived step graph | Loading from a URL, syncing to a shared graph and opening in a browser come with the engine; the known cost is that the artifact is one project's file format, which the stored source and the export offset |
| Lossless bundle (2026-11-03, confirmed 2026-11-08) | Yes: the bundle carries the source byte for byte; the graph is derived, never the other way | Auditors need the program that ran, not only its graph; regenerating source from a graph loses comments and layout |
| Running (2026-11-08) | Load the bundle into memory once, then one Cypher query per step | One body of Cypher serves compile, run, server and console; a step's query costs microseconds against seconds for a model call |
| Runs (2026-11-03) | Never mutate a bundle; recorded to a server or a local store | A bundle is immutable by hash |
| Loops (2026-11-03) | Two forms, independent passes and passes that build on each other, written as blocks with a required cap | Every run terminates in a number of steps computable from the file |
| Answer types (2026-11-06) | A decision writes one key, named by `Produce`, whose fields are its questions; each field is of the question's type, `true_or_false`, `choice` or `score`, an object with `value`, `confidence` and the model's probabilities | Confidence is part of the answer, not a convention beside it; the model's response is kept rather than flattened; nothing to declare |
| Readable syntax (2026-11-06) | Verb first (`Decide triage "..."`, `Route by_tone "..."`, `Execute escalate "..."`, `Task_Agent reply "..."`); every step states `Read`, `Produce` and `Next_Step`; file order carries no meaning; long strings get a name (`x = "..."`) | Active voice reads as a runbook; a step is a self-contained card; reordering a file never changes a procedure; long descriptions stop burying the structure |
| Keyword case (2026-11-06) | Title_Case, underscores between words, braces for blocks; `With`/`On` optional after a step verb; short aliases such as `Next` | Chosen over capitals, which shout at the length of a real procedure, and over a flat SQL-like layout, which needs a keyword on every line and closers on loops. Underscores keep a keyword one token |
| `Aggregate` (2026-11-06) | A step like `Decide`: an `Aggregations` block names each aggregation (`All`, `Any`, `None` over answers, each optionally `== <value>` or `!= <value>` and `With Confidence_Above <p>`) and `Produce` names the one key holding them all. Each result is a `true_or_false` answer **without a confidence**, on purpose. It does not branch; a `Route` reads an aggregation, a `Loop Until` watches one | Combining answers and branching on the result are two things; this keeps them two steps. A joint confidence cannot be computed, so none is written: `docs/language/no-expressions.md` |
| Conditions are on answers (2026-11-06) | A route reads an answer; `Until` takes a condition on one answer, `<answer> [== v \| != v] [With Confidence_Above p]`; aggregation lines take the same condition per answer. No plain `boolean`, `string` or `integer` is ever branched on; a script produces an answer type when a route needs it | One rule for all conditional logic; every confidence check sits on exactly one answer, which is what makes it mean something |
| No expressions (2026-11-06) | No `==`, `&&`, `any()` and the like in routes or gates, even with per-atom confidence and three-valued logic | A compound next to a threshold reads as a joint confidence, which assumes independence that does not hold; `docs/language/no-expressions.md` |
| State (2026-11-06) | One producer per path; a key is rebound only inside a loop body; a second producer elsewhere is an error | Catches accidental overwrites at compile time; gives review loops a correct shape. A scan of 33 existing procedures found none with two producers for any key, so nothing existing is rejected |

## 2. The program

A program is a directory. The source file is at the root, beside three resource directories.

```
ticket-triage/
  procedure.aip
  references/
  assets/
  scripts/
```

### 2.1 The source language

One file, `procedure.aip`, UTF-8. Line comments with `#`. Strings in double quotes. Identifiers are `[a-z][a-z0-9_]*`. Keywords are written in Title_Case, with an underscore between words so a keyword is always one token (`Decide`, `Read`, `Produce`, `Next_Step`, `Answer_Questions`); the compiler accepts them in any case, and the formatter writes them this way. Some have a short alias (`Next` for `Next_Step`), listed in the glossary. Step names, keys, named strings and types (`string`, `choice`, `true_or_false`) stay lowercase, so a reader tells structure from content at a glance.

A keyword is recognised by its position, not reserved: a word that opens a step, a loop, a header line or a clause is a keyword when it spells one, and a word where a name is expected (a key, a step name, a label) is a name. So a key may be called `task` or `history`, and `Read task` reads it. The one exception is `end`, which names the `End` step (section 6, reserved names), and `Continue` as a route target, which always means the pass is over. Newlines carry no meaning: a clause may wrap, a `Produce` may continue on the next line, and a description may sit on the line after `Procedure <name>`; the formatter lays a file out one clause per line.

**Strings.** A double-quoted string may span lines; `\"`, `\\`, `\n` and `\t` are its escapes. A triple-quoted string (`"""..."""`) may also span lines and has no escapes: what is written is what it says. In either, `{key}` or `{decision.question}` is an interpolation (section 2.1, "Questions composed from data"); any other brace is a brace.

**Header.** `Procedure <name> "<description>"`, then the lines that say when the procedure applies: `Use_When`, `Do_Not_Use_When`, `Requires`, `Avoid` (section 6). Each of `Use_When`, `Do_Not_Use_When` and `Avoid` takes one or more strings, on the keyword's line or one per line below it, and may be repeated; `Requires` takes an interpreter and a version (`Requires python 3.10`). The header ends where the first named string, step or loop begins. The start step is written out like any other, so a reader sees the inputs where the procedure begins.

**Names for long strings.** `<name> = "..."` at top level, anywhere in the file, gives a string a name; a step then uses the name where it would have written the string. Strings may span lines in triple quotes. A name holds a string and nothing else: no concatenation, no reference to another name, no use as a key. Unused names are an `info`.

**Steps.** Verb first, then the step's name, then its description, then a block: `<verb> [With|On] <name> "<description>" { ... }`, read as a sentence: *decide triage*, *route by_tone*, *execute escalate*. `With` or `On` may follow the verb when it reads better (`Task_Agent With reply`, `Route On by_tone`); it changes nothing. The keyword names who does the work: a model decides, a script executes, the agent takes a `Task_Agent`, the runtime routes and aggregates. The step name after it is a label, not the work: `Task_Agent reply` is the step called reply, whose prompt may ask for more than a reply. `Start` and `End` have no name, since a procedure has one of each. Every block has three parts in a fixed order, so every step is a card: what it reads (`Read`), what it produces (`Produce`), where it goes (`Next_Step`). Between `Read` and `Produce` come the lines particular to the kind.

| Syntax | Who does the work | Between `Read` and `Produce` |
|---|---|---|
| `Start "..." { <inputs> Next_Step <step> }` | the client supplies the inputs | the inputs as `name: type "description"` lines; it reads nothing and its inputs are what it produces |
| `Decide <name> "..." { ... }` | a decision model, or the agent when allowed | an `Answer_Questions { ... }` block with one question per line (`billing: true_or_false "..."`, `tone: choice [a, b] "..."`, `urgency: score [low, medium, high] "..."`, each with optional indented criteria lines; an instruction may interpolate `{key}` from any key available at the step, so a question is composed from data, such as a policy, while `Read` stays the thing the model judges); `Agent_Fallback true` (optional; absent means false); `History true` (optional); `Produce <key>` names the one key the decision writes, whose fields are the questions (2.4) |
| `Route <name> "..." { ... }` | the runtime, from one answer | `Read <answer>`, one `true_or_false`, `choice` or `score` answer (`triage_decision.tone`, `check_summary.all_hold`, or an answer a script produced); then the check, `Confidence_Below <n> -> <step>`, and one `value -> step` line per label, level or `true`/`false`. No `Produce`. Its branch lines are its `Next_Step` |
| `Aggregate <name> "..." { ... }` | the runtime, from `true_or_false` answers | an `Aggregations { ... }` block with one aggregation per line, `<name>: All\|Any\|None <source> [== <value> \| != <value>] [With Confidence_Above <p>]`, where the source is one answer (`policy_check.pii`), a decision (`policy_check`, every answer in it), a field through a collected list (`verdicts.follows`) or a list collected from an answer key, and its key must be in `Read`; a `choice` or `score` source needs the comparison, a `true_or_false` source without one means `== true`; `Produce <key>` names the one key holding every aggregation, each a `true_or_false` answer with no confidence (2.5) |
| `Execute <name> "..." { ... }` | a script | `Run_Script <path>`, optional `Use` for assets, one per line or comma-separated |
| `Task_Agent <name> "..." { ... }` | the agent | the description is the prompt, or `Prompt <path>`; `Use` for assets and references, one per line or comma-separated; a reference's description follows its path |
| `End "..." { Read ... }` | nobody; it declares the result | `Read` names the result keys; no `Produce`, no `Next_Step` |

`Read` and `Produce` take `name` or `name: type "description"`; a `Read` without a type inherits the producer's type, and every declaration of a key must agree on its type. `Produce` always needs a type, except on a decision, where the type is the shape of its questions. A `Read` may name a field of a decision key, `triage_decision.tone`, and gets that one answer.

**Flow.** Every step says where it goes with `Next_Step <step>`, and `Next_Step end` goes to the end step. A route says it with its branch lines, and must name every value. Because every step names its successor, the order of steps in the file carries no meaning: a reader may group steps however reads best, and reordering a file never changes the procedure. The one structural use of position is a loop, whose body is the block between its braces. The compiler reports a step nothing points at as `unreachable_step`, an error.

A loop's body is the block between its braces, and a pass starts at the first step (or loop) written in it; the order of the rest carries no meaning. Inside a loop body, a step may end in two more ways: `Continue` ends the pass (the loop checks its condition or its count and starts the next pass or exits), and `Again <step>` re-enters the procedure at a step (or a loop) at the level of the enclosing loop, from which the flow reaches that loop again, and follows the flow from there; when the loop is reached the pass is over, as with `Continue`, and the loop keeps its count. So `Again check` in a review loop re-runs the check and every step between it and the loop, which is what makes the loop's condition fresh. `Again` is for a `Loop`, whose passes build on each other; a `For` pass is independent and ends with `Continue`. A route inside a body may send a branch to `Continue` as well as to a step. The loop block itself ends with a `Next_Step <step>` line at block level, for where the procedure goes when the loop exits; a loop nested in another loop's body may end with `Continue` instead, ending the outer pass when it exits. The exit line is the last line of the block and is required (`missing_loop_exit`). A body is closed otherwise: a step inside it leaves it only through `Continue`, `Again` or the loop's exit line, never with a `Next_Step` to a step outside it (`flow_leaves_body`; `End` is not reachable inside a body), and a step outside a body points into it only by naming the loop (`jump_into_body`). Every cycle in the graph therefore passes through a loop body; a flow that closes any other cycle is an error (`cycle_without_loop`).

**Conditions.** All conditional logic in a procedure is on answers (2.4), and it is written one way: `<answer> [== <value> | != <value>] [With Confidence_Above <p>]`. The answer is one `true_or_false`, `choice` or `score` answer; the comparison is against a label, a level or `true`/`false`, and a `true_or_false` answer with no comparison means `== true`; a `choice` or `score` answer requires the comparison. The condition's confidence is the probability the model put on it, from the answer's probabilities, one minus for `!=`. `With Confidence_Above <p>` makes a condition whose probability is below `p`, or that has none, count as false. A condition appears in exactly two places: a loop's `Until`, and each line of an `Aggregations` block, where it is applied to every answer in a source. A `Route` is the other conditional step and uses no condition: it reads one answer, branches on its value, and checks its confidence with `Confidence_Below`. No condition ever combines two answers.

**Loops.** Two forms, each with a required cap so that every run terminates in a number of steps computable from the file:

- `For <name> Over <list> As <item>, At_Most <n> [, Collect <key> Into <list>] { ... }`: independent passes over a list. Every pass stands on its own: it may read the item, its index, and what existed before the loop, and nothing from another pass. `Collect` gathers one key from every pass, in input order; the key may be a decision key, and the list then holds one decision object per pass. The run fails before the first pass if the list is longer than the cap.
- `Loop <name> Until <condition>, At_Most <n> [, Else_Fail|Else_Exit] { ... }`: passes that build on each other until a condition on one answer holds: `Until check_summary.all_hold`, `Until review.verdict == approved With Confidence_Above 0.8`. The loop watches the answer: the condition is tested at the head of every pass and again the moment a step in the body produces the answer (or a loop in the body exits having produced it), and when it holds the loop ends there, skipping the rest of the pass. **An answer that is absent, or a condition below its confidence bar, does not hold**, so the answer need not exist before the loop; it is enough that a step in the body produces it, and the first pass always runs. That is the shape of a check-then-fix loop: check, then fix, with no route between them, because the loop ends at the check that passes (`examples/language/fixed-policy`). It is the same rule as `Confidence_Below`: unknown never counts as a pass. The compiler checks that the answer is produced by a step in the body or before the loop. `Else_Fail` (the default) or `Else_Exit` says what happens at the cap. `Loop <name> <n> Times { ... }` is a counted loop. `Loop <name> Over <list> As <item>, At_Most <n> { ... }` is the fold: passes that build on each other over a list.

A loop has a name because steps reach it with `Next_Step`. Every loop has a cap (`At_Most`, or the count of a `Times` loop), so a run ends in a number of steps computable from the file (`missing_cap`). Inside a body `index` names the pass; after the loop `iterations` says how many ran. Both are the runtime's keys and no step produces them (`reserved_key`). Loops nest; each has its own frame. Every cycle in the graph passes through a loop body, so there are no other cycles.

**Questions composed from data.** A question's instruction may interpolate `{key}` from any key available at the step: `"Does the work follow the policy described below?\n{policy}"`. That composes the question; it does not hand the key to the model as the thing to judge. `Read` is what the model judges. So a decision that checks `work` against a policy reads `work` and writes the policy into its question (`examples/language/fixed-policy`). For availability and lineage an interpolated key counts as a read.

**What the language cannot say** (by design): arithmetic, comparisons other than a condition's `==` and `!=` on one answer, function calls, string building, user-defined types, imports. Field access is not an expression either: a decision key's questions (`triage_decision.tone`) and an answer's `value` and `confidence` are the only fields a procedure can name, and only where 2.4 says. If a procedure needs computation, it is an `Execute` step. The procedure itself is a finite state machine; what makes the system universal is what the steps call out to.

### 2.2 Validation

The compiler checks everything before a bundle exists, and reports against source lines. Much of what a graph validator has to check is unreachable from the language: there is no edge name to get wrong, no cycle outside a loop, and availability of a key at a step is definite assignment over the block structure. What remains meaningful:

- **The state contract.** Every key a step reads is produced on every path to it, or declared on `Start`; every declaration of a key agrees on its type; one producer per path (2.3).
- **Routes, loops and aggregations.** A route reads an answer and names every value it can take; `Until` and every aggregation line hold a condition on an answer, and a plain `boolean`, `string` or `integer` in any of these places is an error (`condition_on_plain_value`). A confidence check or bar sits only on an answer that can carry one (2.4): on an aggregation's output it is an error, `confidence_on_aggregate`, since it has none by design (2.5), and on a script's answer it is the usual warning. A condition's comparison names a label or level the answer's question has (`unknown_label`), and a `choice` or `score` answer without a comparison is an error (`comparison_required`). The compiler classifies what feeds each route as *deterministic* (a script, or an input), *measured* (a model's answer) or *unmeasured* (an agent's hand, or a decision that allows one), and warns when a confidence check guards an unmeasured or deterministic value, neither of which carries a confidence (`confidence_on_unmeasured_source`), or when a route branches on an unmeasured one with no check (`unmeasured_route`).
- **Loops.** The cap is present; a `For` body is independent; nothing outside a body points into it and nothing inside leaves it but through the loop's own lines; `End` is not reachable inside a body; `Until` watches an answer produced before the loop or by a step in its body; a `For` collects only what every pass produces.
- **Resources.** Every script, asset and reference named exists on disk, under `assets/`, `references/` or `scripts/`, the directories the bundle carries; a procedure with `Execute` steps declares `Requires`.

Severities are `error`, `warning`, `info`. Compilation fails on `error` and prints the rest. Every diagnostic has one shape, `{code, severity, message, file, line, column, end_line, end_column, step}`, and `aip compile --check --json <folder>` prints them. The codes, which `aip_spec.CODES` lists in the same order:

| Code | Severity | When |
|---|---|---|
| `syntax_error` | error | the file does not parse; the message names what was expected |
| `missing_start`, `missing_end` | error | no `Start`, no `End` |
| `duplicate_step` | error | two steps or loops share a name, or a second `Start` or `End` |
| `duplicate_name`, `unknown_name`, `unused_name` | error, error, info | a named string defined twice, used but not defined, defined but not used |
| `start_in_loop`, `end_in_loop` | error | `Start` or `End` written inside a loop body |
| `reserved_key` | error | a step produces, or a loop item is called, `index` or `iterations` |
| `missing_clause` | error | a `Decide` without questions or `Produce`, an `Aggregate` without aggregations or `Produce`, an `Execute` without `Run_Script` |
| `missing_type` | error | a `Produce` key of an `Execute` or `Task_Agent` without a type |
| `missing_next_step` | error | a step other than a `Route` or `End` does not say where it goes |
| `question_labels` | error | a `choice` or `score` question without two labels, a `true_or_false` with labels, a label listed twice |
| `duplicate_question`, `duplicate_aggregation` | error | a question or aggregation name used twice in one step |
| `unknown_step` | error | a flow names a step or loop that does not exist (or `start`) |
| `unreachable_step` | error | nothing reaches a step or loop |
| `cycle_without_loop` | error | a flow closes a cycle that passes through no loop body |
| `jump_into_body`, `flow_leaves_body` | error | a `Next_Step` or branch crosses a loop's braces in either direction |
| `continue_outside_loop`, `again_outside_loop` | error | `Continue` or `Again` outside a loop body, or `Continue` as a top-level loop's exit |
| `again_target` | error | `Again` inside a `For`, naming its own loop, or naming a step from which the loop is not reached |
| `missing_cap`, `empty_loop`, `missing_loop_exit` | error | a loop without `At_Most` (or a cap below 1), with no steps, or with no exit line |
| `unknown_key` | error | a key no step produces is read, interpolated, looped over or collected |
| `unavailable_key` | error | a key is read where some path to the step has not produced it, including a `For` body's per-pass key read after the loop |
| `unknown_field` | error | a dotted path names a question, aggregation or field the key does not have |
| `duplicate_producer` | error | a second producer of a key on one path outside a loop (2.3), including a `For` item or `Collect` list named like an existing key |
| `type_mismatch` | error | two declarations of a key disagree, two paths bring different types, or `Over` names something other than a list |
| `route_reads_one` | error | a `Route` reads no key or several |
| `condition_on_plain_value` | error | a route, an `Until` or an aggregation line is on something that is not an answer |
| `missing_branch`, `duplicate_branch` | error | a route lacks a branch for a value, or has two for one |
| `unknown_label` | error | a branch, comparison or criterion names a value the answer cannot take |
| `comparison_required` | error | a `choice` or `score` answer in a condition without `==` or `!=` |
| `confidence_on_aggregate` | error | `Confidence_Below` or `With Confidence_Above` on an aggregation's answer (2.5) |
| `source_not_read` | error | an aggregation's source key is not in the step's `Read` |
| `confidence_on_unmeasured_source` | warning | a confidence check or bar on an answer that may come without one: a decision with `Agent_Fallback true`, an agent task, a script, an input |
| `unmeasured_route` | warning | a route with no check on an answer that may be given by hand |
| `missing_file` | error | a `Run_Script`, `Prompt` or `Use` path is outside the three directories or does not exist |
| `missing_requires` | error | an `Execute` step with no `Requires` in the header |

### 2.3 State: one producer per path

The state is a set of named, typed keys. The language treats it as immutable outside loops and as a fold inside them.

**The rule.** Along any path from `Start` to `End`, a key is written at most once, with two exceptions that are not really exceptions:

- **Alternative branches.** The arms of a `Route` may each write the same key, because exactly one of them runs. After the route the key has one value and one producer, whichever arm ran. In the summary example `draft` and `escalate` both write `reply`.
- **Loop bodies.** A step inside a `For` or `Loop` body may write a key that was written before the loop, or by an earlier pass. Each pass sees the value from the pass before it (or from before the loop, on the first pass); when the loop exits the key is bound once, to the last pass's value. This is the accumulator of a fold. `Again check` re-runs a step and so rewrites that step's keys, which is the same case.

Everything else is an error, `duplicate_producer`, naming both producers and the fix: put the second in a loop, or give it a different name.

**Nothing to declare.** No annotations. The compiler infers which keys a loop threads from the body's `Read` and `Produce` lines: a key the body reads before it writes, and also writes, is carried. A carried key must be available before the loop (that is the fold's initial value), which the availability check proves. In a `For`, whose passes are independent, keys the body writes are per-pass and are gone after the loop unless `Collect` keeps them. In a `Loop`, whose passes build on each other, the state after the loop is the state at the end of the last pass, so every key the body wrote is there, and a step after the loop may read it; the compiler checks that every path through the body up to each place the loop can end writes it, and the first pass always runs.

**What a runtime does.** It rebinds a key when a step writes it, and its run record keeps every step's outputs and attributes each end-state key to the step that produced it, with its pass number inside a loop. Every pass's value stays in the record; only the state's binding moves.

**Why.** Three reasons, in order of weight:

1. An accidental overwrite, two unrelated steps writing `summary`, is a compile error with a line number instead of a surprise in a run log.
2. Authors already behave this way. A scan of 33 existing procedures on 2026-11-06 found no key with two producers. Where a procedure needed a fix pass, its author worked around the lack of a rule by renaming (`body` then `fixed_body`, `rationale` then `rationale_fixed`) and in one case dead-ended the fixed branch so that it never reached the step that would have used the result. The loop form is the shape those procedures wanted.
3. Attribution is simpler: the end-state value of a key has exactly one producer per run, and inside a loop that producer carries a pass number.

**What it costs.** One pattern is not legal: two steps on the same path writing the same key without a loop around them. Nothing in the scan does that.

**Not a functional language.** The language has no functions, no expressions and no values other than state keys; the paradigm word is not used anywhere in product copy. This is one rule about the state, chosen because it is cheap to check and removes a class of mistakes. `For` is a map and `Loop Over` is a fold by name only.

### 2.4 Decision keys and answer types: a decision's result carries its confidence

A decision writes **one key**, named by its `Produce` line, whose fields are its questions; each field's type is the question's type. `Decide triage { ... Produce triage_decision }` writes `triage_decision`, and `triage_decision.tone` is the answer to `tone`. One key per decision keeps the state small, mirrors what a decision model returns (one answer per question), and makes the one-producer rule (2.3) trivial for decisions: the key is the decision's and nobody else's.

**Three answer types.** `true_or_false`, `choice` and `score` join the type vocabulary beside `string`, `integer`, `float`, `boolean`, `list` and `object`. A `Decide` produces them with a confidence; an `Execute` or `Task_Agent` may `Produce` one too (`passed: true_or_false`), and then it has a `value` and nothing else, which is how a script's result enters a route or a loop. Each is an object with the model's own fields kept as the model returns them, plus one field, `value`, the collapsed answer every type has. The reference decision model is TypeSafe, whose answers these are:

| Type | `value` | Model fields |
|---|---|---|
| `true_or_false` | `boolean` | `noul`: the probability of yes, under the model's own field name; `confidence` is `\|2·noul − 1\|` |
| `choice` | `string`, one of the labels | `confidence`; `probabilities`: label to probability |
| `score` | `integer`, the most probable level | `confidence`; `score`: the expected value, a float; `probabilities`: level to probability |

```
triage_decision: {
  billing: {value: true,    confidence: 0.96, noul: 0.98},
  tone:    {value: "angry", confidence: 0.9,  probabilities: {angry: 0.9, calm: 0.1}},
  urgency: {value: 2,       confidence: 0.8,  score: 1.7, probabilities: {"0": 0.1, "1": 0.1, "2": 0.8}}
}
```

A hand-given answer (a decision with `Agent_Fallback true` and no model) is `{value: ...}` and nothing else: no confidence, no probabilities. The decision key's own type in the vocabulary is `decision`; its shape is the compiler's to know from the questions, not the author's to declare. The model's `legend` is dropped; it repeats the question's criteria, which the procedure already has.

**What reads them.**

- A route reads one answer, `Read triage_decision.tone`, and branches on its `value`. Its check, `Confidence_Below <n> -> <step>`, reads the same answer's `confidence`, and fires when that is below the bound or absent. Nothing but an answer can be routed on: a script or an agent task that needs to drive a route produces a key of answer type, `passed: true_or_false`, whose answer has a `value` and no confidence, so a check on it always fires and the compiler says so (`confidence_on_unmeasured_source`).
- Any step may `Read triage_decision` (the whole thing) or `Read triage_decision.tone` (one answer). An `Execute` script receives what it read as it is: `state["triage_decision"]["tone"]["value"]`, or `state["tone"]["value"]` when it read the one answer. A `Task_Agent` step's template names a field: `{triage_decision.tone.value}`. A decision's questions and an answer's `value` and `confidence` are the only field access the language has, and only in a `Read`, a route, a script or a template; `probabilities` and the rest are for the record and for governance, not for the procedure.
- `End` may return a decision key; the result then carries the whole object.

**Why.** Confidence is a property of an answer, not a second key that happens to be named after it. Keeping the model's response whole means the state, the run record and the graph agree, nothing is declared to get it, and `probabilities` reach governance without a format change later.

### 2.5 Aggregate: many answers to one, without a joint confidence

An `Aggregate` is the one place the language combines answers, and it does so under the rule in `docs/language/no-expressions.md`. It has the shape of a `Decide`: a block of named aggregations instead of named questions, and one `Produce` key whose fields are the results.

```
Aggregate summarize_check "Every policy holds, and the model was sure of each." {
  Read policy_check
  Aggregations {
    all_hold:   All policy_check With Confidence_Above 0.7
    any_hold:   Any policy_check
    none_angry: None replies.tone == angry With Confidence_Above 0.8
  }
  Produce check_summary
  Next_Step fix
}
```

1. **Resolve each answer alone, to a condition.** Each answer in the source is tested: `== <value>` or `!= <value>` against a label, a level or `true`/`false`; a `true_or_false` answer with no comparison means `== true`. A `choice` or `score` answer needs the comparison, since it has no yes or no of its own. The condition's confidence is **the probability the model put on the condition**: `probabilities[label]` for `==` on a `choice` or `score`, `noul` or `1 − noul` for a `true_or_false`, and one minus that for `!=`. That is where `!=` is recalculated rather than read off the answer: an answer of calm at 0.6 may be "not angry" at 0.9. When the line says `With Confidence_Above <p>`, a condition whose probability is below `p`, or that has none (a hand-given answer, a `boolean` from a script), does not count as what it says: it counts as whatever makes the aggregation fail, false for `All` and `Any`, true for `None`. So a bar is always fail-closed, and an unsure answer can never pass an aggregation. With no bar, every condition counts as it is. Note the scale: a route's `Confidence_Below` checks an answer's `confidence`, which for a `true_or_false` is `|2·noul − 1|`; an aggregation's bar is on the probability of the condition, which for the same answer is `noul`. The two are different checks with different names on purpose.
2. **Aggregate.** `All`: every resolved value is true. `Any`: at least one. `None`: not one.
3. **Produce.** One key, whose fields are the aggregations. Each is a `true_or_false` answer with a `value` and **no confidence and no probabilities**, on purpose: a confidence for a combination of answers cannot be computed without assuming the answers are independent, and the language refuses to write a number it cannot stand behind. The key's type in the vocabulary is `aggregation`.

An `Aggregate` does not branch. A `Route` reads an aggregation (`Read check_summary.all_hold`) and branches on its value; a `Confidence_Below` on that route is a compile error, `confidence_on_aggregate`. A `Loop Until` may watch an aggregation (`Until check_summary.all_hold`), reading its value, so a check-then-fix loop is check, aggregate, fix with no route (`examples/language/fixed-policy`).

The record keeps each answer's resolution (its value, its confidence, and whether a bar turned it), so governance can ask which answer fails most. For routing, an aggregation is its own source class, *aggregated*: deterministic given the answers, and never guarded by a confidence check.

Every condition is on one answer, and every probability is one answer's. Nothing in an `Aggregate` combines two confidences, which is the line `docs/language/no-expressions.md` draws: `==` and `!=` are per-answer tests, not an expression language, and there is no `&&`, `||` or nesting.

## 3. Compilation: the bundle

The compiler takes a program directory and produces one file, the bundle:

1. Parse `procedure.aip`; syntax errors name line and column.
2. Build the graph and run every check in 2.2.
3. Collect the files under `references/`, `assets/`, `scripts/` with size, mode and sha256.
4. Write the bundle. Its id is the sha256 over the source text and every file's hash, so an unchanged program compiles to the same id on any machine, whatever wrote the file.

The bundle is a [Relate](https://relatedb.ai/) graph database in its single-file form, extension `.rl`. Relate is an embedded property-graph engine with Cypher; the file opens with its CLI, its Python package, its browser build, over Bolt, and loads from a path or a URL. The graph inside holds:

| Nodes | What |
|---|---|
| the procedure | name, language version, compiler version, the bundle id, and the source of `procedure.aip` as text, byte for byte |
| the steps, by kind | each step's name, description and clause values |
| the state's keys, the questions, the aggregations | with their types |
| the files | path, size, mode, sha256 and the bytes, for every file under `references/`, `assets/`, `scripts/` |

and edges for: which step starts and ends the procedure, each step's next step, each route's branches by value and its confidence check, which step produces and which steps read each key, which questions a decision asks, which files a step uses, and the loop structure. The step graph is derived from the source; the source is the program. The schema is written once, with the compiler, in this repository.

The bundle is lossless: exporting it writes the program directory back, byte for byte, and recompiling that yields the same id. A runtime checks that the stored source compiles to the stored graph, so a bundle edited by hand in Cypher does not run. Compilation is fast enough to run on every invocation of a folder: validating and loading a procedure of this size is a few milliseconds.

## 4. Running

- A folder is compiled in memory first; errors stop the run. A bundle is opened, its id and language version checked, and never written.
- A runtime loads the bundle into an in-memory Relate database and reads each step with a Cypher query as it goes. The same queries run against a server's graph.
- Scripts and assets are unpacked once per bundle id into a cache, and executions launch from there.
- A run is recorded with the bundle id on every entry, so that any question about a run can name the exact program that ran.
- `For` passes may run in batches (`--batch N`, default 10), since they are independent; a batch of single-`Decide` passes is one model call. `docs/language/runtime.md` has the full requirements.

What a server does with bundles and runs, how they are projected into a graph database, and how a console shows them are the runtime's concerns, not the language's; `AGENTS.md` says where that work goes.

## 5. Open items

| # | Question | Default |
|---|---|---|
| 1 | Bundle extension | Settled 2026-11-08: `.rl`, the Relate single-file form, so Relate tools open it as is. |
| 2 | Where the description of a `Task_Agent` step ends and its prompt begins | One string: the description is the prompt. A separate `Prompt` line only when the prompt is a file. |
| 3 | `score.value` | The most probable level, an integer, so a route can branch on it; the model's expected value stays beside it as `score`. |
| 4 | `Loop <name> <n> Times` and `For ... At_Most` sugar | Shipped with the language; `Times` is a counted `Loop`. |
| 5 | Qualified reads (`Read triage.tone` meaning "the key `tone`, and assert `triage` produced it") | Not in the language. The one-producer rule already makes the producer knowable; a console can show it. |
| 6 | Graph schema inside the bundle | Written with the compiler; this document describes it in prose only. |
| 7 | `Until All <source> ...` as sugar for an `Aggregate` step | Not now. The explicit step keeps the aggregate in the state and the record, with a description, and keeps `All`/`Any`/`None` out of conditions. Reconsider if loops that wait on an aggregate nobody else reads become common; the sugar would compile to a generated `Aggregate` step. |

## 6. Glossary of keywords

The canonical spelling is Title_Case with an underscore between words. The compiler accepts every keyword in any case (`Next_Step`, `next_step`, `NEXT_STEP` are one keyword), and it accepts the aliases listed here; the formatter rewrites a file to the canonical spelling. Step names, keys, named strings and types are lowercase identifiers and are never keywords.

### Procedure header

| Keyword | Meaning | Aliases |
|---|---|---|
| `Procedure <name> "<description>"` | Opens the file; one per file | |
| `Use_When "..."` | A situation the procedure is for (one string per line) | `Trigger_When` |
| `Do_Not_Use_When "..."` | A situation it is not for | |
| `Requires <interpreter> <version>` | What an `Execute` step needs on the machine | |
| `Avoid "..."` | An anti-pattern for the agent | `Anti_Pattern` |
| `<name> = "..."` | Names a string for use anywhere a string is expected (2.1) | |

### Step kinds

Every step is `<Kind> [With|On] <name> "<description>" { ... }`. `Start` and `End` have no name. `With` or `On` may follow the kind (`Task_Agent With reply`, `Route On by_tone`, `Decide With triage`); it changes nothing and the formatter keeps whichever was written.

| Keyword | Who does the work | Aliases |
|---|---|---|
| `Start` | the client supplies the inputs | |
| `Decide` | a decision model (or the agent, with `Agent_Fallback true`) | |
| `Route` | the runtime, from a value in the state | |
| `Aggregate` | the runtime, from `true_or_false` answers; produces one key of `true_or_false` answers without confidence | |
| `Execute` | a script | |
| `Task_Agent` | the agent | `Task`, `Agent_Task` |
| `End` | nobody; declares the result | |

### Clauses inside a step

In order: what it reads, the lines particular to its kind, what it produces, where it goes.

| Keyword | Where | Meaning | Aliases |
|---|---|---|---|
| `Read <key>[, <key>...]` | every kind but `Start` | the keys the step is given; a key may be `<decision>.<question>` (2.4) | `Reads`, `Input` |
| `<key>: <type> "<description>"` | `Start` | an input the client supplies | `Input <key>: <type>` |
| `Answer_Questions { ... }` | `Decide` | the questions, one per line, each `<name>: <type> [labels] "<instruction>"` with optional indented criteria; an instruction may interpolate `{key}` from any key available at the step, which composes the question without handing the key to the model as data | `Questions` |
| `Agent_Fallback true` | `Decide` | the agent may answer by hand when no model is configured; absent means false | `Fallback` |
| `History true` | `Decide` | the model also sees the run so far; absent means false | |
| `Confidence_Below <n> -> <step>` | `Route` | the confidence check; fires when the read answer's confidence is below `n` or absent | |
| `With Confidence_Above <p>` | on an aggregation line | a condition whose probability is below `p`, or has none, counts against the aggregation; omitted, every condition counts as it is | `w/` for `With`; `Confidence`, `Conf` for `Confidence_Above` |
| `Aggregations { ... }` | `Aggregate` | the aggregations, one per line: `<name>: All\|Any\|None <source> [== <value> \| != <value>] [With Confidence_Above <p>]` | |
| `== <value>` / `!= <value>` | on an aggregation line | the condition each answer is tested against: a label, a level, or `true`/`false`; required for a `choice` or `score` source; its probability comes from the answer's probabilities, `1 −` for `!=` | |
| `Produce <key>` | `Aggregate` | the one key the step writes, whose fields are its aggregations | `Produces`, `Return` |
| `<value> -> <step>` | `Route` | one branch per value of the read key | `When <value> -> <step>` |
| `Run_Script <path>` | `Execute` | the script, launched with the interpreter from `Requires` | `Run`, `Script` |
| `Command "<...>"` | `Execute` | overrides how the script is launched | |
| `Prompt <path>` | `Task_Agent` | the task template; absent, the description is the prompt | `Template` |
| `Use <path> ["<description>"][, <path> ["<description>"]...]` | `Execute`, `Task_Agent` | assets handed to the step, or references with the description of when to load each; several on one line separated by commas, or one `Use` line per item, as reads best | `Uses`, `Asset`, `Reference` |
| `Produce <key>: <type> "<description>"` | `Execute`, `Task_Agent` | a key the step writes; may continue on indented lines | `Produces`, `Return`, `Output` |
| `Produce <key>` | `Decide` | the one key the decision writes, whose fields are its questions (2.4) | `Produces`, `Return` |
| `Next_Step <step>` | every kind but `Route` and `End` | where the run goes; `Next_Step end` is the end step | `Next`, `Go_To` |

### Loops

A loop is `<opener> { <steps> <exit clause> }`; it has a name because steps reach it with `Next_Step`.

| Keyword | Meaning | Aliases |
|---|---|---|
| `For <name> Over <list> As <item>, At_Most <n> [, Collect <key> Into <list>] { ... }` | independent passes over a list; `Collect` gathers one key from every pass in order | `For_Each` |
| `Loop <name> Until <condition>, At_Most <n> [, Else_Fail\|Else_Exit] { ... }` | passes build on each other until a condition on one answer holds, `<answer> [== v \| != v] [With Confidence_Above p]`; tested at the head of each pass and again wherever a body step produces the answer, ending the loop there; absent, or below the bar, does not hold | |
| `Loop <name> <n> Times { ... }` | counted mode: a fixed number of passes | |
| `Loop <name> Over <list> As <item>, At_Most <n> { ... }` | fold mode: passes build on each other over a list | |
| `At_Most <n>` | the cap; required on every loop but a counted one, whose count is its cap | `Max` |
| `Else_Fail` / `Else_Exit` | what an until loop does at the cap; `Else_Fail` is the default | |
| `Continue` | last clause of a step in a body, or a route branch target: the pass is over | `Next_Pass` |
| `Again <step>` | last clause of a step in a `Loop` body: re-enter at a step or loop at the enclosing loop's level and follow the flow until the enclosing loop is reached again, which ends the pass | `Redo`, `Redo_Step` |
| `Next_Step <step>` at block level | where the run goes when the loop exits | |

### Types

Lowercase, never keywords.

| Type | Holds | Aliases |
|---|---|---|
| `string`, `integer`, `float`, `boolean`, `list`, `object` | plain values, as JSON holds them | `number` for `float`, `array` for `list` |
| `true_or_false` | a yes/no answer: `{value: boolean, confidence, noul}` (2.4); from an `Aggregate`, `{value: boolean}` alone (2.5) | `noul` |
| `choice` | a label from a list: `{value: string, confidence, probabilities}` | |
| `score` | a level from a rubric: `{value: integer, confidence, score, probabilities}` | |
| `decision` | what a `Decide` step produces: an object with one answer per question |
| `aggregation` | what an `Aggregate` step produces: an object with one confidence-free `true_or_false` answer per aggregation | |

### Reserved names

`end` as a step target (`Next_Step end`) names the `End` step, and no step may be called `end` or `start`. `index` and `iterations` are the runtime's keys (section 2.1, Loops) and no step produces them. No other identifier is reserved.
