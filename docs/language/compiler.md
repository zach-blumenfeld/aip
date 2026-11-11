# How the compiler works

`aip compile` takes a program directory (`procedure.aip` beside `assets/`, `references/` and
`scripts/`) and produces a bundle: one `.rl` file holding the source byte for byte, the files, and
the graph derived from them (spec section 3; `bundle.md` is the graph's schema, `queries.md` the
queries over it). On the way it produces three other things: the diagnostics, every finding
against a source span; the same graph as JSON (`aip compile --json`), with the spans and without
the contents; and the canonical form of the source (`aip fmt`). Each stage is one module under
`src/aip/compiler/`: the lexer and the parser build the syntax tree (`lexer.py`, `parser.py`,
`syntax.py`); the checker turns the tree into diagnostics (`checker.py`); the graph builder
derives the nodes and edges (`graph.py`); the bundle module computes the id and writes, reads and
verifies the file (`bundle.py`, with `relate.py` the one place the engine is imported); the
formatter writes the tree back as text (`formatter.py`). `cli.py` is `aip compile`, `export` and
`fmt`, dispatched from `aip.client.cli`; `aip info` reads a bundle's graph through the SDK.

The order inside `compile_folder` (`bundle.py`) is: read and decode the source, parse, check
(the file checks look at the folder), stop on any error, collect the files, compute the id, build
the graph, and then, without `--check`, write it. The graph comes after the files and the id
because it carries the id on every node and the files as nodes.

## Tokens and the syntax tree

`lexer.tokenize(source)` returns a list of `Token`s ending in an `EOF` token, of four kinds:
`WORD`, `STRING`, `PUNCT` (`->`, `==`, `!=`, braces, brackets, comma, colon, `=`) and `EOF`. A
word is anything a name, a keyword, a number, a version or a path can be (`triage`, `Next_Step`,
`0.6`, `scripts/escalate.py`); the parser decides which from its position. Newlines are not
tokens, which is why a clause may wrap. A `#` comment rides on the next token (`Token.comments`),
so the parser can hand it to the node it belongs to. Every token carries `line`, `column`,
`end_line` and `end_column` (1-based; the end is the column after the last character). A stray character or an unterminated
string raises `ParseError` here.

`parser.parse(source, file)` is a recursive-descent parser over those tokens; it returns a
`syntax.Program` or raises `ParseError` (`errors.py`) at the first problem, with what was expected
and what was found. `Parser.error()` builds the message and, when the word found is within an
edit or two of a keyword that could stand there (`keywords.nearest`), ends it with `did you mean
Answer_Questions?`. The parser enforces only what is grammar: the shape of each step kind and
loop header, which clauses a kind may carry (`_ALLOWED`) and their order within the card
(`_RANK`: reads, the lines of the kind, `Produce`, the flow), the closed type vocabulary
(`keywords.type_name`) and the reserved name `end`. A keyword is recognised by position through `keywords.keyword()`, in any case and through
its aliases, and stored in its canonical spelling, which is what the formatter writes. Everything
that needs the whole program is the checker's.

The tree (`syntax.py`) is dataclasses. `Program` holds the name, the description, the header
(`HeaderClause`, `Requires`) and `items`, each a `NamedString`, a `Step`, a `ForLoop` or a
`Loop`; a loop's `body` is the same kind of list, and `Program.steps()` yields every step in file
order, bodies included. A `Step` has its `kind`, `name`, `description` and `clauses` in the order
written, one class per clause (`ReadClause`, `QuestionsClause`, `BranchClause`, `FlowClause`,
...), with properties that gather what later passes ask most: `reads`, `inputs`, `produces`,
`questions`, `aggregations`, `branches`, `check`, `flow`, `script`, `prompt`. The small values
are `KeyRef`, `Declaration`, `Condition`, `Flow` and `Text`, which keeps the literal as written
(`raw`) and its `{key}` interpolations (`fields`), each positioned inside the string.

**Spans.** Every node derives from `syntax.Node` and carries `line`, `column`, `end_line` and
`end_column`, set by `Parser.at(node, start_token)`: from the token that opened the node to the
last token consumed. Spans and the `raw` text are declared `compare=False`, so two trees compare
equal when they say the same thing wherever it was written; comments (`leading`, the lines above
a node; `trailing`, at the end of its first line; a block's `end_comments`) do compare, so a
formatter that lost one fails the round trip.

## The checks

`checker.check(program, folder, file, files=, sources=, some_paths=)` returns a list of
`Diagnostic`, sorted by position: `code`, `severity`, `message`, `file`, `line`, `column`,
`end_line`, `end_column` and `step`, the step or loop the finding is in. `CODES` maps every code
to its severity, in the order of the spec's 2.2 table, which is the list of codes.
`report()` makes one, dropping an exact repeat; `report_head()` anchors a finding about a whole
step or loop to its opening keyword. A syntax error becomes a diagnostic one level up:
`check_source()` catches `ParseError` and returns `Diagnostic(**exc.to_diagnostic())` as the only
finding, code `syntax_error`; `compile_folder` reports a source that is not UTF-8 the same way.

`Checker.run()` is the walk, in this order:

1. **Index** (`index()`): every step and loop by name, bodies recursed with the loops around
   them (`region_of`). Here `duplicate_step`, `duplicate_name` (a named string twice),
   `start_in_loop`, `end_in_loop`, `reserved_key` on a loop's name, then `missing_start` and
   `missing_end`.
2. **Each step on its own** (`check_step()`): the clauses its kind needs (`missing_clause`,
   `missing_type`, `missing_next_step`, a route with no lines at all), its questions and their
   labels, its produced keys against the reserved and loop names, and its files through
   `check_file()`, which requires a path under `RESOURCE_DIRS` and then looks on disk, or in the
   `files` set when the program's files are in hand (a bundle's). After the loop, `missing_requires` on the first `Execute`.
3. **Regions and flow** (`region()`): the top level, then each loop body as the walk reaches
   it, with the loops inside a region as single nodes. `successors()` resolves every `Next_Step`,
   branch, check target and `Continue`: `unknown_step`, `flow_leaves_body`, `jump_into_body`,
   `continue_outside_loop`, `missing_loop_exit`. `_topo()` is a depth-first search from the
   region's entry giving the topological order and the back edges: a node not in the order is `unreachable_step`, a back edge `cycle_without_loop`.
   With a flow unresolved (`self.broken`) no `unreachable_step` is reported: it would be its consequence.
4. **The state**, node by node in that order. Two states reach every node, each a dict of key to
   `Entry(type, producers, inside)`: the **must-state**, `meet()`, the keys every incoming path
   brings, types merged (`type_mismatch` at the join when paths disagree), and the
   **may-state**, `_join()`, the keys any path brought. `visit_step()` reads from the must-state:
   `check_reads()`, the interpolations of a question or a prompt (`check_text()`, which count
   as reads), a route, an aggregate.
   `resolve()` walks a dotted path through `Type.field()` and reports `unknown_field`; a missing
   root goes to `report_missing()`: `unavailable_key` when something in the file produces the
   key (or it is a loop's or the runtime's), `unknown_key` otherwise. `End` is the one step read
   against the may-state: a key in the may-state but not the must-state is a result "on some
   paths", which `check(..., some_paths=)` hands back for `aip info`. Then `produce()` writes the
   step's keys into both states: a key that already has a producer `inside` this region is
   `duplicate_producer`; one whose producer is outside (before the loop) may be rewritten.
5. **Loops** (`visit_loop()`): the cap (`missing_cap`), the item (`bind_item()`; `Over` needs a
   list, `type_mismatch`), then the body as a region of its own, entered through `_reset()`,
   which clears every `inside` so a body may rewrite what came before the loop, plus `index` and
   the loop's own key. What the loop leaves is computed from the body's exit points. A `For`
   leaves the state before it plus the collected list (`collected()`). A `Loop` leaves the meet
   of every exit: each `Continue`, and for an `Until` loop (`check_until()`) every body node
   that produced the answer and the head itself when the answer may exist before the loop (spec
   2.6). The pass keys are dropped, `iterations` and the loop's key added.
6. **Routes, conditions, aggregations.** `check_route()`: `route_reads_one`,
   `condition_on_plain_value`, `unknown_label` (the wrong branch lines in one report, which then
   silences `missing_branch`), `duplicate_branch`, `missing_branch`. `check_aggregate()`:
   `source_not_read`, then `answers_of()` expands a source into its answers and
   `check_condition()` tests each (`comparison_required`, `unknown_label`). `unused_name` comes last.

**Source classes.** Every `Type` carries `sources`, the steps whose answer it is, merged at
joins. `classify()` maps them through `SOURCE_CLASSES` by step kind (spec 2.2), and
`check_confidence()` reports `confidence_on_agent_answer`, `confidence_on_input` or
`confidence_on_aggregate` for a `Confidence_Below` or a `With Confidence_Above` on a class that
cannot carry one. `source_class()` picks the least measured class in `SOURCE_PRECEDENCE` when a
route's arms produced one key from steps of different kinds; `check_route` records it in
`self.sources[route]`, which `check(..., sources=)` fills for the graph.

## The graph

`graph.build_graph(program, files, bundle_id, compiler_version, sources)` turns a checked tree
into a `Graph`: `nodes`, each a `GraphNode(id, labels, properties)`, and `edges`, each a
`GraphEdge(type, start, end, properties)`. It decides nothing the checker has not accepted; the
`sources` it is handed are the checker's. `_Builder.build()` indexes the items (name to id, and
the loops at each nesting level), writes the `Procedure` node from the header, one `File` node
per `FileEntry` (`path`, `size`, `mode`, `sha256`, and `text` when the bytes are UTF-8, else
`base64`) with `HAS_FILE`, then walks the items: `step()` for a step, `loop()` for a loop, which
recurses into its body with the path extended.

**Ids** come from `_node_id`: `step:<name>` (`step:start`, `step:end`), `loop:<name>`,
`data:<key>`, `question:<step>.<question>`, `aggregation:<step>.<aggregation>`, `file:<path>`,
and `procedure`. The prefix names the label the node is found by (`bundle.py`'s `ID_LABELS`),
which is how an edge's ends are matched when the graph is written. Every node gets `id` and
`bundle_id`; `_clean()` drops null properties; `edge()` drops exact duplicates and adds the span
of the clause passed as `at=`.

A `Data` node is made on first use by `key()`, with `SUPPLIES` from the procedure; the first
declaration that says a type, a description or labels fills them in. A `Read` or an
interpolation goes through `read()`: `(Data)-[:READ_BY]->(Step)` with `field` (the dotted rest
of the path), `interpolated: true` for a `{key}`, and on a `Route` the `source` class. The
runtime's keys get their producer there too: `index` is `PRODUCES` by the innermost loop,
`iterations` by every loop at the reader's level, and a loop's own key (`revise.iterations`) by
that loop; those `Data` nodes are `runtime: true`. Otherwise `PRODUCES` comes from a `Produce`
line, a `Start` input or a `For`'s collected list (type `list`); a `Decide`'s key is type
`decision`, an `Aggregate`'s `aggregation`.

Flow is `flow()`: `NEXT` for a `Next_Step`, `CONTINUES` for a `Continue`, pointing at the
enclosing loop; a route's lines are `BRANCH {value}` and `BELOW {below}`, with `continues: true`
when the target is `Continue`. A target that does not exist is skipped, not an error, which is
what `--partial` relies on. A loop node carries `Loop` (and `For` on a `For`), `HAS_LOOP` from the
procedure, `OVER` to the list, `BINDS` to the item, `COLLECTS` and the `PRODUCES` of the list,
`WATCHES` to the `Until` answer with the condition's parts, `CONTAINS {order}` to every body item
in written order, `ENTERS` to the first one, and its exit line as a `NEXT` or `CONTINUES` from
the loop node. `CONTAINS` is membership, not flow: a walk over control flow uses `ENTERS` and
`CONTINUES` and leaves it out (`queries.md`, Control flow).

## The bundle

`bundle.compile_folder(folder, source=None)` runs the pipeline and returns `(Bundle | None,
diagnostics)`: a `Bundle` (`name`, `source`, `files`, `graph`, `id`, `language_version`,
`compiler_version`) when there is no error, `None` otherwise, the diagnostics either way.
`source` stands in for the file's text when given (`--stdin`, an editor's unsaved buffer); the
files still come from disk. `compile_source(source, files, file, compiler)` is the same with the
files in hand, checked against that list instead of the disk; `read_bundle` and the tests use
it. `collect_files()` walks the three resource directories, sorted, skipping
`__pycache__` and `.DS_Store`.

**The id.** `bundle_id(source, files)` hashes a manifest: the line `aip bundle 1`, `source` and
the sha256 of the source's UTF-8 bytes, then `file <path> <sha256>` for every file sorted by
path, newline-terminated; the id is the sha256 of that text. Only the source and the files'
bytes enter it: not a file's mode, not the compiler's or the language's version, not the time,
not the `.rl`'s own bytes. `_assemble()` computes the id, builds the graph with it, writes the
source onto the `Procedure` node (the builder leaves it null; the bundle owns the bytes) and
makes the `Bundle`; `compiler_version()` is the installed package's.

**Writing.** `write_bundle(bundle, path)` opens a new file through `relate.create()` and calls
`write_graph(conn, graph, bundle_id)`, the one body of Cypher that puts a graph in a store: one
`UNWIND ... CREATE` per label set, then one per edge type that matches both ends by label and
`{bundle_id, id}`. The same function fills the engine's in-memory copy and a server's store, where many bundles
share one graph. `relate.py` imports the engine lazily (`relate`, or the pinned release's
`cypherlite`) and knows the suffix. Nothing imports it at package load, so `aip compile --check`, `--json` without a bundle and `fmt` run without Relate; `compile`
exits 3 when writing needs it.

**Reading and verification.** `read_bundle(path)` opens the file read-only and reads the one
`Procedure` node (`not_a_bundle` when there is not exactly one, it lacks `bundle_id` or `source`,
or the file is not Relate's), then `read_graph()` for every node and edge under that id. A
`language_version` other than `LANGUAGE_VERSION` is `bundle_language_version`; an edge type in
`RETIRED_EDGES` (`AGAIN`) is `bundle_format`. Then
three checks, each `bundle_tampered` when it fails: every `File` node's bytes hash to the
`sha256` and `size` recorded on it; the stored source and files hash to the stored id; and the
stored source compiles, through `compile_source` with the stored file list and the stored
`compiler_version`, to a graph whose `canonical()` (nodes and edges sorted, so order does not
count) equals the stored graph's. Handing the rebuild the stored version is how the compiler's
version stays out of the comparison; nothing else is excluded. `export_bundle()` writes `procedure.aip` and every file
back with its mode (`export_target` when the directory is in use and not `--force`).

**`--partial`.** `partial_graph(folder, source)` is for an editor drawing a change half done.
When the source parses, it runs the checker anyway and builds the graph from the tree with
`_assemble()` as if the errors were not there: an edge to a step that does not exist is left out
(`flow()` skips it), a `Data` node for a key nothing produces is still made, and a tree the
builder cannot build from gives `None`. It is never a bundle: no id, never written. The CLI
prints it as `graph` with `partial: true`, `ok` false and `bundle_id` null; a file that does not
parse gets `graph: null, partial: false`.

## The formatter

`formatter.format_program(program)` writes a tree back as text; `format_source(source, file)`
parses first. **Canonical form** is: keywords in their canonical spelling, two-space indent, one
clause per line, a blank line between the items of the file and between the steps of a loop
body, none between the clauses of a step; strings written exactly as the author wrote them
(`Text.literal()` returns the `raw` text, so nothing is re-escaped); the `With` or `On` after a
step kind kept; comments back where they were. `Writer` also aligns columns: a route's arrows, a
typed `Produce` (one key per line), a question block's types, a run of named strings' `=`.
**Named strings** are written where they were: those with `before_header` set come first, above
the `Procedure` line, the rest stay among the items, and consecutive ones are grouped with no
blank line between them.

The property the tests hold is `parse(format_program(parse(x))) == parse(x)` for every `x` that
parses, and that formatting is idempotent. `aip fmt --check` decides by string equality:
`format_source(text) == text` is `unchanged`, anything else `would reformat`, and the command
exits 1 when any file would change or does not parse. `aip fmt --stdin` prints the canonical form
of standard input. The examples must be
canonical (`aip fmt --check examples/language` in CI): formatting changes the source, and so the id.

## What `aip compile --json` emits

One object: `procedure`, `file`, `ok`, `bundle_id` (null unless `ok`), `language_version`,
`compiler_version`, `output` (the `.rl` written, or null), `diagnostics`, `graph`
(`Graph.to_dict(content=False)`: no `source`, `text` or `base64`; null when there is no bundle,
unless `--partial` supplied one), and with `--partial` the key `partial`. A node is `{id, labels, properties}`, an edge `{type, start, end, properties}`; a span is four
properties, `line`, `column`, `end_line`, `end_column`, 1-based with the end after the last
character, on every step, loop, question and aggregation (and the procedure), and on the edges a
clause wrote. From `examples/language/billing-support`, with `bundle_id` cut short:

```json
{"id": "step:by_tone", "labels": ["Step", "Route"],
 "properties": {"id": "step:by_tone", "bundle_id": "d2631813…", "name": "by_tone", "kind": "Route", "description": "…",
                "line": 48, "column": 1, "end_line": 53, "end_column": 2, "check_below": 0.9}}
{"type": "READ_BY", "start": "data:triage_decision", "end": "step:by_tone",
 "properties": {"field": "tone", "source": "measured", "line": 49, "column": 8, "end_line": 49, "end_column": 28}}
{"type": "BRANCH", "start": "step:by_tone", "end": "step:escalate",
 "properties": {"value": "angry", "line": 51, "column": 3, "end_line": 51, "end_column": 20}}
```

A diagnostic has one shape, here from a copy of the same example with a branch pointed at a
step that does not exist:

```json
{"code": "unknown_step", "severity": "error",
 "message": "Next_Step replyy: no step or loop is called replyy",
 "file": ".../procedure.aip", "line": 52, "column": 12, "end_line": 52, "end_column": 18, "step": "by_tone"}
```

**Editors.** The VS Code extension (`editors/vscode/src/compiler.js`) runs
`aip compile --check --json --stdin` on the buffer and turns each diagnostic into a squiggle,
subtracting one from `line`, `column` and `end_column` for VS Code's zero-based ranges; its
preview jumps the editor to a node's `line`. The console's Studio (`console/bin/aip-console.mjs`,
`POST /console/studio/check`) runs `aip fmt --stdin` and then `aip compile --check --json
--partial --stdin` on what the page holds, so the graph keeps drawing while a change is half
done; `console/src/studio/edit.ts` turns a form edit into a text replacement at a node's or an
edge's span (end exclusive), and the page re-checks, so the graph is always what the compiler
made of the text. Nothing in an editor edits the graph.

## Extending it

- **A label, a property or an edge** is added in `docs/language/bundle.md`, in `graph.py` and in
  `tests/test_bundle.py` in one commit; a new id prefix also goes in `bundle.py`'s `ID_LABELS`,
  and an edge type that is dropped goes in `RETIRED_EDGES` with what replaced it, so an older
  bundle is refused by name. Then look at who reads the graph: `src/aip/model/procedure.py`,
  `src/aip/server/store.py`, `skill.py`, and `console/` and `editors/vscode` where they draw it.
- **A diagnostic code** is added to `CODES` in `checker.py` and raised through `report()` or
  `report_head()` at the node whose span it should carry; to the table in spec 2.2
  (`tests/test_check.py::Examples.test_every_code_is_in_the_spec` fails otherwise); to the
  skill's list, "Mistakes the compiler will name" in `skills/aip/references/language.md` (whose
  copy under `examples/language/make_procedure/assets/` means compiling `make_procedure` again);
  and to `EveryCode.test_each_code_is_reported_at_its_position`. Keep "one mistake, one error":
  a finding that follows from another is silenced the way `self.broken` and `self.keyless` do.
- **A keyword or alias** is `keywords.py` and the spec's glossary, in the same commit.
- **Versions.** `LANGUAGE_VERSION` (`language.py`) and the compiler's version are written on the
  `Procedure` node and printed in the report; neither enters the bundle id, which is the source
  and the files alone. A bundle of another
  language version is refused on open before anything is verified. A change to what `graph.py`
  writes makes every older bundle `bundle_tampered` on open, which is why a graph change is a
  language-version change, or, for a dropped edge, a `RETIRED_EDGES` entry.

## Reading order

1. `syntax.py`: the tree every later pass reads.
2. `keywords.py`, then `lexer.py` and `parser.py`: how text becomes that tree.
3. `checker.py`: `CODES`, `Checker.run()`, then `region()`, `visit_step()`, `produce()` and
   `visit_loop()`, with spec 2.2, 2.3 and 2.6 beside them.
4. `graph.py`: `_Builder.step()` and `loop()`, with `bundle.md` open.
5. `bundle.py`: `compile_folder()`, `bundle_id()`, `write_graph()`, `read_bundle()`; `relate.py`.
6. `formatter.py`: `Writer`. Then `cli.py`, and the tests: `tests/test_parse.py`,
   `test_errors.py`, `test_check.py`, `test_bundle.py`, `test_format.py`.
