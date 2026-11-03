# The AIP procedure format

Format version `0.6a1`. This is the specification of an AIP skill: the folder, the `SKILL.md`
file, the YAML procedure inside it, and the rules the validator enforces. The source of truth
is the pydantic model in [`src/aip_spec/models.py`](../src/aip_spec/models.py); the JSON Schema
at [`skills/aip-compile/assets/procedure.schema.json`](../../../skills/aip-compile/assets/procedure.schema.json)
is generated from it (`aip-spec schema`), and a test fails if the two drift. Where this page and
the model disagree, the model wins.

Contents: [the skill folder](#the-skill-folder) · [`SKILL.md`](#skillmd) · [the procedure](#the-procedure) ·
[steps](#steps) · [state and data flow](#state-and-data-flow) · [types](#types) · [validation](#validation) ·
[versioning](#versioning) · [the Python package](#the-python-package)

## The skill folder

An AIP skill is an [Agent Skill](https://agentskills.io/specification) folder with one more
required directory, `source/`, and a `SKILL.md` body in a fixed shape.

```
skill-name/
├── SKILL.md          required: frontmatter, the runtime block, one YAML procedure
├── source/           required: the human-readable material the skill was compiled from
│   └── README.md     recommended: provenance, and what was left out on purpose and why
├── scripts/          optional: code that `execution` steps run
├── assets/           optional: templates and files that steps inject
└── references/       optional: documents a `client_task` may load on demand
```

Every path a step names (`script`, `template`, `assets`, `references`) is relative to the skill
folder, must start with its directory's name (`scripts/`, `assets/`, `references/`), and must
exist on disk.

## `SKILL.md`

Two parts: YAML frontmatter between `---` lines, then the body.

### Frontmatter

The Agent Skills fields, plus one AIP key under `metadata`.

| Field | Required | Rule |
|---|---|---|
| `name` | yes | 1–64 characters, lowercase `a–z`, `0–9` and hyphens, no leading, trailing or doubled hyphen; equal to the folder name |
| `description` | yes | 1–1024 characters; what the skill does and when to use it |
| `metadata.aip-version` | yes | the format version the skill is written in, as a string: `"0.6a1"` |
| `metadata.*` | no | any other string-to-string entries, such as `author` or `version`; keys starting `aip-` are reserved |
| `license` | no | a string |
| `compatibility` | no | 1–500 characters; environment requirements, when the skill has any |
| `allowed-tools` | no | a string; experimental in Agent Skills |

### Body

The body is exactly two things, in order, and nothing else:

1. **The runtime block**, verbatim. It is the text `aip-spec runtime` prints
   ([`src/aip_spec/runtime.md`](../src/aip_spec/runtime.md)): a heading `# AIP runtime — format 0.6a1`
   and the execution semantics any agent needs to run the procedure with no AIP tooling present.
   The validator compares the skill's copy to the package's and rejects a missing or edited one.
2. **One fenced YAML block** holding the procedure described below.

No prose before, between or after them, and no second code block. The bundled example,
[`examples/billing-support/SKILL.md`](../../../examples/billing-support/SKILL.md), is a complete skill
in this shape.

## The procedure

The YAML block is one mapping, `ProcedureSpec`. Every object in the format is closed: an
unknown key is an error.

| Key | Required | Type | Meaning |
|---|---|---|---|
| `purpose` | yes | string | what the procedure encapsulates and what it adds beyond general agent knowledge; one short paragraph |
| `trigger_when` | yes | list of strings, at least one | conditions under which an agent should consider the skill |
| `do_not_use_when` | no | list of strings | explicit non-purposes |
| `requires` | when there are `execution` steps | [`Requires`](#requires) | what the machine running the scripts must have |
| `steps` | yes | list of [steps](#steps), at least two | the execution graph |
| `anti_patterns` | no | list of strings | mistakes the procedure steers the agent away from |

The graph: the first entry of `steps` is the **start** and must be runnable (`decision`,
`execution` or `client_task`). Exactly one step has `kind: end`. Each runnable step names the
step that receives its output in `inputs_to`; a `router` names its successors in `branches`.
Step names are unique, kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`), and every reference resolves to
one of them. Every step is reachable from the start and can reach the end.

### `Requires`

| Key | Required | Rule |
|---|---|---|
| `interpreter.name` | yes | the program that runs the scripts, as found on PATH: `python`, `bash`, `node` |
| `interpreter.version` | no | minimum version, dotted numbers (`"3.10"`) |
| `packages` | no | Python distributions the scripts import, as pip names, optionally `name>=version` |
| `tools` | no | other executables the scripts call or are launched with, each checked on PATH |

An agent checks `requires` before the first script and stops, naming everything missing.

## Steps

Every step has `name`, `kind` and `description` (one line; optional on `end`). The other keys
depend on `kind`.

### `execution`: a script runs

| Key | Required | Rule |
|---|---|---|
| `inputs` | yes | the state keys the script reads; see [`IOItem`](#ioitem) |
| `script` | yes | path under `scripts/` |
| `outputs` | no, default empty | the keys the script adds to the state; a script that adds nothing is unusual |
| `command` | no | the argument list that launches the script, run from the script's folder (`["bash", "run.sh"]`); omitted, the script runs as `python <script>`. The first item must be the `requires` interpreter or one of its `tools` |
| `assets` | no | paths under `assets/`, re-read on every run and handed to the script |
| `timeout` | no | seconds, greater than zero |
| `inputs_to` | yes | the next step |

The script receives one JSON object on stdin, `{"state": <the step's inputs>, "assets":
{<file stem>: <content>}, "expects": <the next step's inputs>}`, and writes one JSON object to
stdout holding exactly its declared `outputs`. A non-zero exit, or output missing a declared
key, fails the step.

### `decision`: typed questions about the state

| Key | Required | Rule |
|---|---|---|
| `inputs` | yes | the content being judged |
| `questions` | yes, at least one | a mapping of question name (`^[A-Za-z_][A-Za-z0-9_]*$`) to a [question](#questions) |
| `thresholds` | no | question name to a number in `[0, 1]`: the review threshold for that question |
| `history` | no, default `false` | also give the decision model the run so far, not only the declared inputs |
| `inputs_to` | yes | the next step |

A decision's outputs are its question names: each answer collapses to one value under its
name. For a `noul` the threshold flags an answer whose probability is within that margin of
0.5; for `choice` and `score` it flags an answer whose confidence is below it. A flagged answer
is reconsidered, by the agent running the skill or by a client with a human in the loop.

#### Questions

Three kinds, discriminated by `type`. `instructions` carry the criteria; the step's `inputs` are
what is being evaluated.

| `type` | `criteria` | the answer, as it lands in the state |
|---|---|---|
| `noul` | optional `true` and `false` descriptions of what counts as each | `boolean` |
| `choice` | a mapping of at least two labels to a description (or `null` when self-explanatory) | `string`, one of the labels |
| `score` | an ordered list of two to ten level descriptions, lowest first | `integer`, the level's position starting at 0 |

Quote labels that YAML would read as booleans (`"yes"`, `"no"`, `"on"`, `"off"`).

### `client_task`: the agent does the work

| Key | Required | Rule |
|---|---|---|
| `inputs` | yes | the state keys the template may use |
| `template` | yes | path under `assets/`; rendered with `{key}` from the inputs, `{assets[stem]}` for its assets, `{meta.name}` for the skill name |
| `outputs` | yes | the keys the agent's answer must contain; the validator rejects a client task without them (`missing_outputs`) |
| `assets` | no | paths under `assets/`, available to the template as `{assets[stem]}` |
| `references` | no | list of `{path, description}`, `path` under `references/`; loaded only if the agent decides the description applies |
| `framing` | no, default `true` | prepend the AIP framing (which workflow this is, how to read the state) to the rendered task |
| `inputs_to` | yes | the next step |

### `router`: branch on a value

| Key | Required | Rule |
|---|---|---|
| `branch_on` | yes | a state key, typically a question name or an output |
| `branches` | yes, at least two | value to step name |

A router reads `branch_on` and continues at `branches[value]`; a value with no branch is an
error. It adds nothing to the state. When `branch_on` is a decision question, the branch keys
must be values that question can produce: its labels, `true`/`false`, or level numbers written
as strings (`"0"`, `"1"`).

### `end`: the result

| Key | Required | Rule |
|---|---|---|
| `inputs` | yes | the keys handed back as the procedure's result |

### `IOItem`

Each entry of `inputs` and `outputs`:

| Key | Required | Rule |
|---|---|---|
| `name` | yes | the key in the state |
| `type` | yes | one of the [types](#types) |
| `description` | no | one line; recommended, it makes the graph readable without opening the script or template |

## State and data flow

The state is one JSON object a run carries. It starts as the start step's `inputs`, which the
caller supplies, and each step adds its outputs to it. The validator enforces, across every
path through the graph:

1. **Every consumed key is produced.** A key a step reads (`inputs`, or a router's `branch_on`)
   is produced by a step on every path to that step, or declared on the start step. A key
   produced on one branch only cannot be read after the branches join (`unproduced_input`). A
   router's confidence `key` need only be produced on some path to it: where it is absent at
   runtime the check fires.
2. **One type per key.** Every declaration of a key agrees on its type: an `IOItem` type for a
   start input, an input or an output, `boolean`/`string`/`integer` for a noul/choice/score
   answer, `float` for a confidence key and a router's confidence `key`. The first declaration
   in step order is the reference (`type_mismatch`). A router branches on a `boolean`, `string`
   or `integer` (`unbranchable_type`).
3. **A step sees only its declared inputs.** The agent gives it those keys and nothing else.

A key may have more than one producer, the start step included: keys accumulate, and where a
run passes through two producers the later one overwrites the value. The validator says so as
information (`duplicate_producer`, severity `info`), never as a fault.

### The sources of a route

What feeds a router's `branch_on` is classified, per router, from every producer of the key
from which the router can be reached; with several producers the worst class wins:

| Class | Source |
|---|---|
| deterministic | a start input, or a script's output when the router reads no confidence the script declares |
| measured | a decision with `fallback: false` whose `confidence` list names the branch question, with the router checking `<question>_confidence`; or a script or client task whose outputs include the number the router checks |
| unmeasured | a decision with `fallback: true`, a decision whose confidence is not emitted or not checked, or a client task output the router does not check: probabilistic, with no calibrated number behind it |

A router with a confidence check on an unmeasured source gets `confidence_on_unmeasured_source`
(a warning: the check reads a number nothing calibrated); a router with no check on an
unmeasured source gets `unmeasured_route` (a warning: a probabilistic choice routed the run and
nothing recorded how sure it was); a router checking a confidence a script or client task
declared itself gets `declared_confidence` (information: legitimate for calibrated code,
discouraged for an agent's task, which cannot calibrate its own confidence). A deterministic
source reports nothing. `aip_spec.classify_sources(spec)` returns the class per router, and
`validate_skill` carries it on the loaded skill as `routers`, so a server can store it.

## Types

The vocabulary for `type` on inputs and outputs. The runtime compiles them to JSON Schemas and
checks the state before a step runs and the step's result after.

| `type` | JSON |
|---|---|
| `string` | string |
| `integer` | integer |
| `float` | number |
| `boolean` | boolean |
| `object` | a key/value map |
| `list[*]` | an array of any of the above |

## Validation

```bash
aip-spec validate <skill-folder>
```

Exit 0 when valid (warnings and information allowed), 1 on any error. One human line on
stdout; on stderr, one JSON record per issue: `path`, `kind`, `message`, optional `location`
(`$.name` in the frontmatter, `body:$.steps[2].inputs_to` in the YAML) and optional `severity`
(absent means error; `warning` or `info` otherwise). The same checks run in Python as
`aip_spec.validate_skill(folder)`.

What is checked, in order, and the `kind` each failure reports:

| Area | Checks |
|---|---|
| folder | the path is a directory holding `SKILL.md` (`file_not_found`, `not_a_directory`, `missing_skill_md`); `source/` exists (`missing_source_dir`) |
| frontmatter | present and a mapping (`missing_frontmatter`, `invalid_frontmatter`); the rules in the table above (`missing_required_frontmatter`, `invalid_name`, `name_mismatch`, `invalid_description`, `invalid_compatibility`, `invalid_license`, `invalid_allowed_tools`, `invalid_metadata`); `metadata.aip-version` present and current (`missing_aip_version`, `aip_version_mismatch`, `runtime_block_outdated` for a recognised earlier format) |
| body | the runtime block, verbatim, then exactly one fenced YAML block (`empty_body`, `missing_runtime_block`, `invalid_body_format`); the YAML parses to a mapping (`invalid_body_yaml`, `invalid_body`) |
| schema | the mapping validates as `ProcedureSpec`; each pydantic error is one `schema_violation` with its location |
| graph | unique step names (`duplicate_step_name`); exactly one start (`missing_start_step`, `multiple_start_steps`) that nothing hands off to (`edge_into_start`); exactly one end (`missing_end_step`, `multiple_end_steps`); every `inputs_to`, branch target and confidence check `to` exists (`unknown_step_reference`); every step reachable from the start (`unreachable_step`) and able to reach the end (`no_path_to_end`); a decision's `confidence` list names its own questions (`unknown_confidence_question`); a router fed by a decision branches only on values it can produce (`unknown_branch_value`); unique input and output names per step (`duplicate_input_name`, `duplicate_output_name`); every `script`, `template`, asset and reference exists (`missing_resource`) |
| state | the data-flow rules (`unproduced_input`, `type_mismatch`, `unbranchable_type`); every `client_task` declares `outputs` (`missing_outputs`); several producers of one key, as information (`duplicate_producer`) |
| sources | the class of each route (`confidence_on_unmeasured_source` and `unmeasured_route` as warnings, `declared_confidence` as information) |
| environment | a procedure with `execution` steps declares `requires` (`missing_requires`); each `command` starts with the interpreter or a declared tool (`undeclared_launcher`) |

## Versioning

`FORMAT_VERSION` in `models.py` is the format version; a skill's `metadata.aip-version` must
equal it. The runtime block's heading carries the same version, so a change to the block is a
change to the format. The validator also recognises the versions in `LEGACY_VERSIONS`: a skill
in one of them is reported as a single `runtime_block_outdated` naming the edits it needs, as a
warning when the current format still accepts that version (none today: `0.8` is breaking) and
an error when it does not (`0.5a1`, `0.6a0`, `0.6a1`; for `0.6a1` the message names
`aip upgrade`). The upgrades themselves are in the repository's
[`docs/upgrading.md`](../../../docs/upgrading.md).

The format's version moves only when the format changes; the package version
(`aip-spec`, the same as `agent-instruction-protocol`) moves every release. The rules are in
the [roadmap](https://github.com/zach-blumenfeld/aip/issues/20) and, with the release
process, in the repository's `AGENTS.md`.

## The Python package

```python
from aip_spec import validate_skill, load_skill, ProcedureSpec, json_schema, runtime_text, example_dir, skill_dir

loaded, issues = validate_skill("./billing-support")   # LoadedSkill | None, list[Issue]
spec = ProcedureSpec.model_validate(yaml_mapping)      # the model itself
schema = json_schema()                                  # the JSON Schema dict
```

`aip_spec` imports only pydantic and pyyaml. `LoadedSkill` holds the parsed frontmatter, the
`ProcedureSpec`, and the skill folder; `Issue.to_record()` is the JSON record the CLI prints.
`skill_dir()` is the bundled `aip-compile` skill and `example_dir(name)` a bundled example.
