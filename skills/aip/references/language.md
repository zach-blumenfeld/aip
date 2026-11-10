# The AIP procedure language on one page

A procedure is a folder: `procedure.aip` beside `assets/` (prompt templates and files a step is
handed), `references/` (files an agent loads only when needed) and `scripts/` (what `Execute`
steps run). `aip compile --check <folder>` checks all of it and names every mistake with its
line; `aip fmt <folder>` rewrites the file in the canonical form. The full definition is
`docs/language/spec.md` in the aip repository, and its section 6 is the list of every keyword.

## A whole procedure

```aip
Procedure ticket_triage
  "Classify a batch of support tickets, draft replies, escalate the uncertain ones."

  Use_When "A batch of support tickets needs replies."
  Requires python 3.10

classify_question = "What kind of ticket is this and how does the customer sound?"

Start "The batch of tickets and the policy every reply must follow." {
  tickets: list  "The tickets, one string each."
  policy: string "The policy a reply must follow."
  Next_Step each_ticket
}

For each_ticket Over tickets As ticket, At_Most 50, Collect reply Into replies {
  Decide classify classify_question {
    Read ticket
    Answer_Questions {
      billing: true_or_false "Is this a billing question?"
      tone:    choice [calm, angry] "How does the customer sound?"
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
    Next_Step revise
  }

  Execute escalate "Open a ticket in the tier-2 queue." {
    Read ticket
    Run_Script scripts/escalate.py
    Produce reply: string
            queue: string
    Continue
  }

  Loop revise Until passed, At_Most 4, Else_Fail {
    Execute check "Does the reply quote the policy correctly?" {
      Read reply, policy
      Run_Script scripts/policy_check.py
      Produce passed: true_or_false
      Next_Step fix
    }

    Task_Agent fix "Revise the reply so it quotes the policy correctly." {
      Read reply, policy
      Produce reply: string
      Continue
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

## The rules that matter

- **Keywords are Title_Case, names are lowercase.** Step names, keys and named strings are
  `[a-z][a-z0-9_]*`. Comments start with `#`. Strings are in double quotes, or in triple quotes
  when they span lines. `some_name = "..."` at top level names a long string, and a step uses the
  name where it would have written the string.
- **The header** is `Procedure <name> "<description>"`, then `Use_When`, `Do_Not_Use_When`,
  `Avoid` (each takes one or more strings) and `Requires python 3.10`, all before the first step.
  A procedure with an `Execute` step must have `Requires`.
- **Every step is a card with a fixed order**: `Read`, the lines of its kind, `Produce`, then
  where it goes. Every step but a `Route` and `End` ends with `Next_Step <step or loop>` (or
  `Next_Step end`); inside a loop body it may end with `Continue` instead.
- **The order of steps in the file means nothing**; only `Next_Step` and branches do. A step
  nothing points at is an error. There is exactly one `Start` and one `End`, and neither has a name.
- **A key has one producer on any path.** Two steps may produce the same key only when they are
  on different paths, or when the second is inside a loop body (it then replaces the value
  each pass). A step other than `End` may read only keys that every path to it has produced.
  `End` may read a key that only some paths produce, and the result carries what the path
  taken produced.
- **There are no expressions**: no arithmetic, no `and`/`or`, no string building. Anything
  computed is a script in an `Execute` step.

## Step kinds

| Kind | Who does it | Its own lines |
|---|---|---|
| `Start "..." { ... }` | the caller | inputs, one per line, `key: type "description"`; then `Next_Step` |
| `Decide <name> "..." { ... }` | a decision model, never the agent | `Answer_Questions { ... }`, one question per line; `Produce <key>` with no type: the key's fields are the questions |
| `Route <name> "..." { ... }` | the runtime | `Read` of exactly one answer, then one `<value> -> <target>` line for every value it can take, and optionally `Confidence_Below 0.8 -> <target>`; no `Produce`, no `Next_Step` |
| `Aggregate <name> "..." { ... }` | the runtime | `Aggregations { all_hold: All verdicts.follows With Confidence_Above 0.7 }` (`All`, `Any` or `None` over answers); `Produce <key>` with no type |
| `Execute <name> "..." { ... }` | a script | `Run_Script scripts/x.py`; optional `Use assets/config.json` |
| `Task_Agent <name> "..." { ... }` | the agent running the procedure | the description is the prompt, or `Prompt assets/task.md`; optional `Use assets/policy.md` and `Use references/help.md "when to load it"` |
| `End "..." { Read ... }` | nobody | `Read` names the result keys; nothing else |

A task for a person is a `Task_Agent` whose description says so: the agent takes it to them and answers with what they decided.

Types: `string`, `integer`, `float`, `boolean`, `list`, `object`, and the three answer types
`true_or_false`, `choice [a, b]` and `score [low, medium, high]` (at least two labels each).

## Answers, routes and conditions

Only an **answer** can be branched on or tested: a `true_or_false`, a `choice` or a `score`.

- A `Decide` asks a decision model. A question is `key: true_or_false "..."`, `key: choice [a, b]
  "..."` or `key: score [low, medium, high] "..."`, optionally followed by indented criteria
  lines (`angry: "Frustrated or demanding."`). Its answers are `classification.tone`, each with a
  value and a confidence. The question text may interpolate any key available at the step,
  `"...{policy}"`, whether or not the step reads it, to compose the question from data; `Read`
  is what the model judges.
- A `Decide` needs a decision model configured on the machine that runs. When the agent should
  judge instead, use a `Task_Agent` that produces an answer type: `Produce tone: choice [angry,
  calm] "..."`. A script does the same with `Produce passed: true_or_false`.
- A `Route` reads one answer (`Read classification.tone`, or `Read passed`) and has a branch for
  every label, or for `true` and `false`. A target is a step, a loop, `end`, or `Continue` inside
  a loop body. `Confidence_Below` is allowed only on a `Decide`'s or a script's answer, never on
  an agent's, an input or an aggregation.
- A condition, used by `Until` and by each line of `Aggregations`, is on one answer:
  `<answer>` (a `true_or_false`, meaning it is true), `<answer> == <label>` or `<answer> !=
  <label>`, optionally `With Confidence_Above 0.7`. Two answers are never combined in a
  condition; an `Aggregate` step combines many into one, and a route or a loop reads that.
- A `Read` may name a whole key (`classification`), one answer (`classification.tone`) or its
  plain value (`classification.tone.value`). A route reads the answer itself, never `.value`.

An `Aggregate` is a card like any other. Here `verdicts` is the list a `For` collected with
`Collect verdict Into verdicts`, and `verdict` is the key of a `Decide` in its body with one
question, `follows`:

```
Aggregate summarize_check "Every policy holds, and the model was sure of each." {
  Read verdicts
  Aggregations {
    all_hold: All verdicts.follows With Confidence_Above 0.7
  }
  Produce check_summary
  Next_Step fix
}
```

The source's key must be in the step's `Read`. The result is read as `check_summary.all_hold`,
by a route or by `Loop revise Until check_summary.all_hold`; it is true or false and has no
confidence, so nothing puts a `Confidence_Below` or a `With Confidence_Above` on it.

## Loops

Every loop has a name, a cap, a body between braces, and an exit line as the last line of the
block (`Next_Step <step>`, or `Continue` when it is nested in another loop's body). A pass
starts at the first step written in the body. A step in a body goes to another step of the same
body, or ends the pass with `Continue`; nothing jumps into or out of a body.

| Header | Use it for |
|---|---|
| `For <name> Over <list> As <item>, At_Most <n>, Collect <key> Into <list> { ... }` | the same steps for every item, each pass on its own; what a pass produces is gone after the loop unless `Collect` keeps it |
| `Loop <name> Until <condition>, At_Most <n>, Else_Fail { ... }` | check and fix until an answer holds; `Else_Exit` leaves the loop at the cap instead of failing the run |
| `Loop <name> <n> Times { ... }` | exactly `n` passes that build on each other |
| `Loop <name> Over <list> As <item>, At_Most <n> { ... }` | one pass per item, each seeing what the one before wrote |

The cap counts passes of the body: `At_Most 3` on a `Loop` is at most three passes. A `For`
given a list longer than its cap fails the run before the first pass, so its cap is the most
items the procedure should accept.

`Until` is tested before every pass, the first included, and again the moment a body step
produces the answer. So a loop that checks and fixes has one shape, the check inside it: the
body is the check, then the fix ending in `Continue` (`check` and `fix` in `revise` above). The
loop ends at the check that passes, so no route is needed between them and work that passes the
first check never reaches the fix. The check may be several steps (a `For`, then an
`Aggregate`). A fix is checked by the next pass, so a fix made in the last pass the cap allows
is never checked: for `n` checked fixes write `At_Most n+1`.

## Prompts and scripts

- A `Task_Agent` prompt (the description, or the `Prompt` file) may interpolate the step's `Read`
  keys as `{key}` or `{decision.question.value}`, and the text of a `Use` asset as
  `{assets[stem]}` (`Use assets/policy.md` is `{assets[policy]}`). A value that is not a string
  (a list, an answer) is written into the prompt as JSON. Say in the prompt what to answer with:
  the agent answers with exactly the step's `Produce` keys.
- A script is launched with one JSON object on stdin, `{"state": {<the Read keys>}, "assets":
  {<stem>: <text of each Use file>}, "expects": {<its Produce keys and types>}}`, and prints one
  JSON object on stdout holding exactly its `Produce` keys. A non-zero exit fails the step. An
  answer-typed key is written as the bare value (`{"passed": true}`). Files it reads or writes
  by relative path belong under the directory in the `AIP_WORKDIR` environment variable.
- Every `Run_Script`, `Prompt` and `Use` path must exist under `scripts/`, `assets/` or
  `references/` of the folder.

## Mistakes the compiler will name

`unreachable_step` (nothing points at it), `unknown_step`, `missing_next_step`, `missing_branch`
(a route without a line for some value), `unknown_key` and `unavailable_key` (read but not
produced on every path), `duplicate_producer` (two producers on one path outside a loop),
`condition_on_plain_value` (a route or `Until` on a `string` or `boolean`; produce an answer
type instead), `confidence_on_agent_answer`, `missing_cap`, `missing_loop_exit`,
`flow_leaves_body` (a step in a loop body with a `Next_Step` to a step outside it, `Next_Step
end` included; it ends with `Continue` and the loop's exit line goes on; a check that a fix
must go back to is written inside the loop, and the clause that once jumped back to a step
before the loop is a `syntax_error` saying it "is gone: write the step inside the loop and end it
with `Continue`"), `missing_type`
(a `Produce` of an `Execute` or `Task_Agent` without a type), `missing_requires`, `missing_file`.
Fix the first error first; one mistake is reported once, and fixing it may reveal the next.
