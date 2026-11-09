# The bundle and its graph

What `aip compile` writes (spec section 3): one Relate file, extension `.rl`, holding the
program's source byte for byte, its files, and the graph derived from them. This page is the
schema of that graph. `aip_spec/graph.py` is its only implementation and `aip_spec/bundle.py`
writes and reads the file; a label, property or edge added here is added there in the same
commit, and the tests under `packages/aip-spec/tests/test_bundle.py` hold the two together.

The same graph is what `aip compile --json` prints (without the source and file contents, with
every span) and what a server projects into its store.

## Identity

Every node carries two properties: `id`, unique within the bundle, and `bundle_id`, so a store
holding many bundles can match any node by the pair.

| Node | `id` |
|---|---|
| the procedure | `procedure` |
| a step | `step:<name>`; the `Start` step is `step:start`, the `End` step `step:end` |
| a loop | `loop:<name>` |
| a key of the state | `key:<name>` |
| a question | `question:<decide>.<question>` |
| an aggregation | `aggregation:<aggregate>.<aggregation>` |
| a file | `file:<path>`, the POSIX path from the program directory (`assets/policy.md`) |

**The bundle id** is the sha256 of a manifest listing the sha256 of the source and of every file:

```
aip bundle 1
source <sha256 of procedure.aip's bytes>
file <path> <sha256 of its bytes>        one line per file, sorted by path
```

An unchanged program compiles to the same id on any machine and whatever wrote the file; the
`.rl`'s own bytes, a file's mode, the compiler's version and the time never enter it.

Steps, loops, questions and aggregations carry their source span: `line`, `column`, `end_line`,
`end_column` (1-based, the end after the last token). Flow edges and the edges a clause wrote
carry the span of that clause. A property whose value would be null is left out.

## Nodes

| Label | Properties |
|---|---|
| `Procedure` | `name`, `description`, `language_version`, `compiler_version`, `bundle_id`, `source` (the text of `procedure.aip`), `use_when`, `do_not_use_when`, `avoid` (lists of strings), `requires_interpreter`, `requires_version` |
| `Step` and the kind: `Start`, `Decide`, `Route`, `Aggregate`, `Execute`, `Task_Agent`, `End` | `name`, `kind`, `description`; a `Decide`: `agent_fallback`, `history`, `produces` (the decision key); a `Route`: `check_below`; an `Aggregate`: `produces`; an `Execute`: `script`, `command`; a `Task_Agent`: `prompt` (a path; absent, the description is the prompt) |
| `Loop`, and `For` on a `For` loop | `name`, `kind` (`For` or `Loop`), `mode` (`Over`, `Until` or `Times`), `item`, `at_most`, `times`, `at_cap` (`Else_Fail` or `Else_Exit`), `collect_key`, `collect_into`, `until_answer` (dotted), `until_operator`, `until_value`, `until_confidence_above` |
| `Key` | `name`, `type` (a word of the type vocabulary when the program says it: `decision` for a decision key, `aggregation`, `list` for a collected list), `description`; `runtime: true` on `index` and `iterations` |
| `Question` | `name`, `type`, `labels`, `instruction` (the text, named strings resolved), `criteria_labels`, `criteria_texts`, `order` |
| `Aggregation` | `name`, `mode` (`All`, `Any`, `None`), `source` (dotted), `operator`, `value`, `confidence_above`, `order` |
| `File` | `path`, `size`, `mode` (the permission bits), `sha256`, and the contents: `text` when the bytes are UTF-8, else `base64` |

## Edges

| Edge | From → to | Properties | Meaning |
|---|---|---|---|
| `HAS_STEP`, `HAS_LOOP`, `HAS_KEY`, `HAS_FILE` | `Procedure` → each | | what the bundle holds |
| `STARTS_AT`, `ENDS_AT` | `Procedure` → `Start`, `End` | | where a run begins and ends |
| `NEXT` | `Step` → `Step` or `Loop`; `Loop` → `Step` or `Loop` | span | `Next_Step`; from a loop, its exit line |
| `CONTINUES` | `Step` → the enclosing `Loop`; nested `Loop` → outer `Loop` | span | `Continue`: the pass is over; from a nested loop, its exit line |
| `AGAIN` | `Step` → `Step` or `Loop` | span | `Again <step>` |
| `BRANCH` | `Route` → `Step` or `Loop` | `value`; `continues: true` when the branch is `Continue` (then the target is the enclosing loop); span | one `<value> -> <step>` line |
| `BELOW` | `Route` → `Step` or `Loop` | `below`; `continues: true` as for `BRANCH`; span | `Confidence_Below <n> -> <step>` |
| `PRODUCES` | `Step` → `Key`; `Loop` → `Key` | span | a `Produce` line or a `Start` input; a `For` produces its `Collect Into` list; a loop produces `index` and `iterations` where a step reads them |
| `READS` | `Step` → `Key` | `field` (the dotted path after the key, `tone` in `triage_decision.tone`), `interpolated: true` for a `{key}` in a question or prompt; span | `Read`, and interpolation, which counts as a read |
| `ASKS` | `Decide` → `Question` | `order` | |
| `AGGREGATES` | `Aggregate` → `Aggregation` | `order` | |
| `OVER` | `Aggregation` → `Key`; `Loop` → `Key` | `field`; span on a loop | an aggregation's source; the list a `For` or a fold iterates |
| `BINDS` | `Loop` → `Key` | | the item key (`As <item>`) |
| `COLLECTS` | `For` → `Key` | span | the per-pass key gathered by `Collect` |
| `WATCHES` | `Loop` → `Key` | `field`, `operator`, `value`, `confidence_above`; span | the `Until` condition's answer |
| `CONTAINS` | `Loop` → `Step` or `Loop` | `order` | the body, in written order |
| `ENTERS` | `Loop` → `Step` or `Loop` | | the first node of the body, where a pass starts |
| `RUNS` | `Execute` → `File` | | `Run_Script` |
| `PROMPTED_BY` | `Task_Agent` → `File` | | `Prompt` |
| `USES` | `Step` → `File` | `description` (a reference's); span | `Use` |

## Reading a bundle

`aip export <bundle.rl> --out DIR` writes the program directory back, byte for byte, with each
file's mode. Before anything is read from a bundle, it is verified: the bytes of every file hash
to their recorded `sha256`, the source and files hash to the recorded `bundle_id`, the stored
source parses and checks against the stored file list, and the graph it compiles to equals the
stored graph (the compiler's version is the one property left out of the comparison). Any
difference is `bundle_tampered`, so a bundle edited by hand in Cypher does not export and does
not run. A bundle of another language version is `bundle_language_version`; a file Relate cannot
open, or one without exactly one `Procedure`, is `not_a_bundle`.

In Cypher, the bundle answers as any Relate store does:

```
MATCH (s:Step) RETURN count(s)
MATCH (r:Route)-[b:BRANCH]->(t:Step) RETURN b.value, t.name
MATCH (p:Procedure) RETURN p.name, p.bundle_id, size(p.source)
```
