# AI-rewrite prompt template

Reusable prompt for producing an **AI-optimized companion** to a human-prose
document — same content, restructured so another LLM can ingest it with
minimum tokens, minimum parsing latency, and maximum decision-clarity.

Works on any document in any repo. Nothing in this template is specific to
a project, codebase, or workflow.

## Why bother — the bigger picture

Per-doc compression is the tactical win (smaller files, faster reads).
The strategic win is **schemas as process encoding**: once a class of
human reasoning artifacts (deliberations, specs, runbooks, post-mortems)
all validate against the same shape, the corpus becomes machine-tractable
in ways no individual doc ever is.

Concretely, a fleet of schema-validated AI-rewrites enables:

- **Pattern mining across decisions.** "Every option we rejected for
  'speculative' reasons" or "every lean that depended on a synergy with
  another item" becomes a one-line extraction over the corpus, not a
  doc-trawling expedition.
- **Decision archaeology.** Six months later, "why did we reject
  option X?" is a structured lookup
  (`items.*.options.X.verdict_reason`), not "find the doc and re-read
  400 lines of prose."
- **Schema-to-schema translation.** When `deliberation` and `spec`
  schemas both exist, an agent can derive a draft spec from a settled
  deliberation by mapping fields (`lean.pick → spec.scope`,
  `open_questions[answer=*] → spec.invariants`,
  `options[verdict=rejected].verdict_reason →
  spec.alternatives_considered`). Stage handoffs become mechanical
  instead of judgment-laden.
- **Cross-team / cross-org transfer.** A shared schema is a lingua
  franca. Another team's deliberation in this format is field-level
  diffable against yours, not "kinda similar to how we do it."
- **Process meta-analysis.** "Did deliberations whose `lean` was
  followed ship faster than ones overridden mid-flight?" becomes a real
  question instead of an anecdotal vibe — *if* deliberation, spec, and
  release docs all carry schema-validated structure.
- **Structured training data.** A fleet of schema-validated
  deliberations is high-quality structured input for fine-tuning a
  team-specific reasoning assistant — far more useful than the same
  content as freeform markdown.
- **Catches silent bugs.** A bonus benefit, but a real one. The first
  time we ran the deliberation schema validator, it surfaced two
  failures in the rewrite that had been silently invisible: an
  unparseable nested block, and seven list items where YAML was
  parsing `- Word: rest` as a one-key map instead of a string.
  Consumer agents would have seen `{"honest layering": "..."}` where
  the writer intended a string. Schema validation makes that class of
  bug catchable instead of latent.

The reframe: AI-rewrites are not "smaller copies of human docs." They
are **structured representations of human reasoning that downstream
agents can compose, query, and learn from.** The compression is
incidental; the structure is the asset.

### Beyond the file: ingesting into Neo4j

Schema-validated YAML is already machine-tractable, but it lives on
disk as N independent files. Loading the corpus into a graph database
turns "compose, query, learn from" into single-line Cypher.

The pipeline is set up under [`mapper/`](mapper/) and
[`schemas/`](schemas/):

- **`schemas/deliberation.gql`** — forward-looking GQL graph type
  declaration. The single declarative source for the deliberation
  graph type once Neo4j's `CREATE GRAPH TYPE` feature is GA.
- **`schemas/deliberation.cypher`** — current-day equivalent
  (constraints + indexes). Run once per Neo4j database before first
  ingest.
- **`mapper/mapper.py`** — takes `(JSON Schema, AI-rewrite YAML,
  original markdown)` as input, validates, and emits idempotent Cypher
  that materializes the structured content as a graph. The original
  markdown becomes a `:SourceDocument` node (with full prose under a
  fulltext index), so any consumer can traverse one edge to fall back
  from structure to original context.
- **`mapper/README.md`** — pipeline overview, usage, idempotency
  scheme, example queries, limitations.

Lossy mode only — the lossless `context:` TAIL has no graph
representation in v1 and would need its own schema + mapper.

The cross-doc value lands as soon as you ingest more than one rewrite:
the `refs:` map in each YAML becomes `[:REFERENCES]` edges to other
`:SourceDocument` nodes (creating stubs for not-yet-ingested docs and
upgrading them in place when those docs are later added). That seeds
the process-knowledge graph.

### Future direction: schemas that link to each other

The biggest unrealized value comes from **referenceable links between
schemas** — a `spec.derived_from → deliberation`, a
`release.implements → spec`, an `incident.regresses → release`. That
turns the docs from a flat collection into a graph of organizational
reasoning, where queries like "every shipped release that implements a
spec with unresolved open_questions" or "every incident that traces back
to a deliberation that picked the lean over a 'tentative' alternative"
become possible.

Not in scope for this template today, but a deliberate design
direction: **schema fields should reference paths in sibling schemas
when they exist**, so the eventual links don't require breaking
changes. (E.g., a future `spec.schema.json` should have a
`derived_from: { type: 'string', description: 'path to a
deliberation-schema doc' }` field, ready to be machine-followed.)
The mapper would translate that field into a typed edge
(`[:DERIVED_FROM_DELIBERATION]`) targeting the deliberation's
`:AiRewrite` node, completing the cross-schema graph.

## What this is for

Some documents are read by *both* humans and agents: design docs,
deliberation notes, requirements specs, architecture references, runbooks.
The human version optimizes for narrative flow, rhetorical scaffolding,
and re-readability. An agent reading the same content wastes attention on
those affordances — transitions, restated context, polite hedging.

This template produces an **AI-companion file** (e.g. `ai-discussion.md`,
`ai-spec.md`, `ai-runbook.md`) that lives next to the original. The
original stays canonical for humans; the AI version is what an agent
should be pointed at when context budget or processing latency matters
(long planning sessions, many docs in context, sub-agent fan-out).

The two are kept in sync manually — when the human doc updates
materially, re-run this template against it. (This is the cost of the
pattern. Worth it for high-traffic docs; not worth it for one-off notes.)

## Output is schema-constrained

AI-rewrite output validates against a JSON Schema in
[`schemas/`](schemas/). The schema family is **strict-core,
open-extensions**: every object has a closed key set (no surprise
keys, no inconsistent naming across docs), but each object also
allows an optional `extensions:` map for doc-specific structure
that doesn't fit the core. This gives consuming agents predictable
shape without making the schema brittle.

Available schemas:

- [`deliberation.schema.json`](schemas/deliberation.schema.json) —
  for AI-rewrites of deliberation / discussion docs. Strict.
  Required core: `items → options → pros/cons/verdict → lean →
  open_questions`.
- [`generic.schema.json`](schemas/generic.schema.json) — loose
  fallback for sources that don't fit a doc-type-specific schema
  (yet). Required minimum: `doc`, `schema`, `status`. Use
  reluctantly — predictability is the point of the family, and
  generic-schema'd output gives consumers fewer guarantees.

The output file declares which schema it follows via a top-level
`schema:` key (`schema: deliberation`, `schema: generic`, etc.).
Consuming agents can dispatch on this; tooling can validate via
`ajv` or any standard JSON Schema validator (YAML parses to the
same data structure JSON Schema expects).

Adding a new doc-type schema: scaffold one alongside the existing
schemas, follow the strict-core/open-extensions pattern, and add it
to the list above.

Validation one-liner (uses the YAML head of the AI-rewrite as input):

```bash
uv run --with pyyaml --with jsonschema python3 -c '
import yaml, json, sys
from jsonschema import Draft202012Validator
schema = json.load(open(sys.argv[1]))
text = open(sys.argv[2]).read()
body = text.split("---", 2)[1] if text.startswith("---") else text
doc = yaml.safe_load(body)
errs = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.absolute_path))
print("VALID" if not errs else f"{len(errs)} errors:")
for e in errs[:20]:
    print(f"  {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:200]}")
' docs/workflow/schemas/<schema>.schema.json <ai-rewrite-file>
```

YAML hazard: list items shaped like `- Word: rest` get parsed as
one-key maps, not strings. Use an em-dash (`—`) or a different
separator in the body content. The validator catches this — if you
see `is not of type 'string'` errors on `pros`/`cons`/list items,
that's the cause.

## Two modes: lossy vs lossless

**Lossy mode (default).** Drops rhetorical scaffolding, narrative pacing,
and any content judged not decision-relevant. Produces the smallest file.
Use when the consumer only needs to act on the decisions / facts and
won't be asked to reconstruct the source's reasoning, tone, or motivating
context.

**Lossless mode.** Same compressed HEAD as lossy mode, plus a `context:`
TAIL with anchor-keyed blocks that preserve everything the lossy version
would have dropped — original phrasings, hedging that carried meaning,
emphasis-via-repetition signals, motivating anecdotes. HEAD items
reference TAIL anchors via a `ctx: [...]` field. Bigger than lossy, but
the *full* source meaning is recoverable.

When lossless is worth it:
- The source uses italics/bold/repetition as load-bearing emphasis (lost
  in plain compression).
- Downstream agents may need to mirror the original author's framing or
  voice (e.g., generating user-facing copy from a spec).
- The doc is part of a long-lived deliberation trail where "why we cared"
  matters as much as "what we decided."
- Consumers can selectively read (sub-agent that excerpts the HEAD; RAG
  retrieval against context anchors). For a single-shot consumer that
  ingests the whole file regardless, lossless is just a bigger file —
  pick lossy.

The `Mode:` placeholder in the prompt below picks between them.

## Workflow

1. **Pick a target doc.** Should be one that's (a) reasonably stable
   (re-running on a doc that changes weekly is busywork) and (b) gets
   read by agents in long-context or fan-out scenarios where token cost
   compounds. Mature reference docs, settled deliberation notes, and
   stable specs are the sweet spot. Drafts and personal notes are not.
2. **Decide the output path.** Convention: same directory as the source,
   prefixed `ai-`. So `path/to/discussion.md` → `path/to/ai-discussion.md`.
   Co-location keeps the pair discoverable; the prefix makes the
   relationship obvious. Override the convention if your project already
   has a different one — just be consistent.
3. **Paste the prompt below** into a fresh agent session, filling the
   placeholder block.
4. **Spot-check the output.** This is not a deliberation stage — there's
   nothing to iterate. Verify: (a) every option/decision/constraint from
   the source survives; (b) no new claims were introduced; (c) cross-refs
   resolve. If something material is missing, point at it specifically and
   re-run; don't argue with the agent about format choices.
5. **Commit both files together** when the source doc changes
   materially. Drift is the failure mode.

## The prompt

```
Produce an AI-optimized companion file for an existing human-prose
document. Final output: a single new file at the target path that
conveys the same decision-relevant content as the source, restructured
for minimum token cost and minimum parsing latency when read by
another LLM.

==========================================================
USER INPUTS (fill these in)
==========================================================

Source doc (path):  <SOURCE_PATH>
                      # The human-prose document to compress.

Schema:             <SCHEMA>
                      # Which schema in docs/workflow/schemas/ the
                      # output should validate against. Pick the
                      # tightest one that fits the source:
                      #   deliberation — for discussion / deliberation
                      #                  docs (items → options → lean)
                      #   generic      — loose fallback for anything
                      #                  that doesn't fit a tighter
                      #                  schema. Use reluctantly.
                      # Default: agent picks based on source shape
                      # and reports the choice.

Mode:               <MODE>
                      # Either:
                      #   lossy     — drop rhetorical scaffolding,
                      #               narrative pacing, anything not
                      #               decision-relevant. Smallest file.
                      #   lossless  — same compressed HEAD plus a
                      #               `context:` TAIL with anchored
                      #               blocks preserving everything the
                      #               lossy version would have dropped.
                      # Default: lossy.

Output path:        <OUTPUT_PATH>
                      # Convention: same dir as source, prefixed `ai-`
                      # e.g. path/to/discussion.md
                      #   → path/to/ai-discussion.md
                      # For lossless, append `-lossless`:
                      #   → path/to/ai-discussion-lossless.md

Audience profile:   <AUDIENCE>
                      # Default: "another frontier-class LLM in a
                      # long-context planning or sub-agent task."
                      # Override only if the consumer is a smaller /
                      # different model with different parsing
                      # strengths.

Lossy-OK content:   <LOSSY_OK>
                      # Categories the user is fine dropping. Default:
                      # rhetorical scaffolding, narrative arcs, polite
                      # hedging, repeated context, anecdotal asides.
                      # Add overrides here if you want some of those
                      # preserved (rare).

Lossy-NOT-OK:       <LOSSY_NOT_OK>
                      # Categories that MUST survive verbatim or with
                      # zero loss. Default: option names, verdicts,
                      # code/cypher/SQL snippets, file paths,
                      # identifiers, numerical thresholds, "rejected
                      # because X" rationale, open questions.

Project glossary:   <GLOSSARY>
                      # Optional. Project-specific terms / acronyms /
                      # ID schemes that the source uses without
                      # defining inline (e.g. "B.x = retrieval query
                      # ids defined in retrieval-queries.md"). Helps
                      # the agent decide what's safe to abbreviate.
                      # Leave empty if the source is self-contained.

==========================================================
AGENT INSTRUCTIONS (do not edit)
==========================================================

1. Read the source doc end-to-end before writing anything. Note:
   - every option / decision / verdict / lean
   - every cross-reference (file paths, ids, schema terms)
   - every constraint or non-negotiable
   - every open question
   - every concrete artifact (code, queries, paths, numbers)

   These are the load-bearing units. Everything else (transitions,
   re-explanations, narrative pacing) is candidate for compression.

1a. Pick the schema. Read docs/workflow/schemas/ and pick the
    tightest schema that fits the source. If the user supplied
    <SCHEMA>, use that. If not, default to `deliberation` for
    docs structured as "options + tradeoffs + lean," `generic`
    only when no doc-type-specific schema applies. Report the
    choice in your final summary.

    The output MUST validate against the chosen schema. The
    schema is strict-core / open-extensions: every object has
    a closed key set, but each object accepts an `extensions:`
    map for doc-specific structure that doesn't fit the core.
    Use `extensions:` SPARINGLY — most content should fit the
    core. If you find yourself reaching for `extensions:` in
    every option, the schema is wrong for this doc; pick a
    different schema or flag the misfit in your report.

2. Output format: YAML, validating against the chosen JSON Schema.

   The schema dictates structure; this section is about the
   formatting choices the schema doesn't constrain.

   a. YAML over JSON. JSON Schema doesn't care about serialization;
      YAML parses to the same structure with less syntactic
      overhead (no quotes, no commas, multiline strings via `|`).
   b. Identical shape across siblings. The schema enforces this
      for the closed core (every option must have name/action,
      etc.); apply the same discipline within `extensions:` —
      if you use a custom key on one option, use it on its
      siblings where it would also apply.
   c. Definitions once, references many. Put repeated terms in
      the `glossary:` block at the top. Reference them as opaque
      tokens after that.
   d. Critical issues escalated to named keys, not buried in
      prose. If a "con" is actually a correctness bug, use the
      structured-cons form (`cons:` as a map with named entries
      like `critical_section_correctness:`) rather than the flat
      string-list form.

3. Compression rules (apply in BOTH modes — produce the HEAD):

   - Strip rhetorical scaffolding. "That's the right call for the
     working path. But it leaves..." → just the constraint.
   - Replace paragraph transitions with structural keys. The reader
     doesn't need "First, ... Second, ..." when keys give the same
     ordering for free.
   - De-duplicate context. If the source restates a scenario three
     times for human pacing, state it once.
   - Eliminate hedging that doesn't carry information. "Doable, but
     a schema rethink" → just keep "schema rethink required".
   - Keep concrete artifacts inline (code snippets, paths, numerical
     values). Compressing those is false economy — the downstream
     agent needs them verbatim.
   - Preserve "rejected because X" rationale. Knowing an option
     was considered and rejected is decision-relevant; silently
     omitting it loses the reasoning trail.

3a. ADDITIONAL rules for lossless mode (produce the TAIL):

   After the compressed HEAD, append a `context:` section with
   anchor-keyed blocks. Every place the lossy mode would have
   dropped meaningful content, instead:
     (i)  add a `ctx: [<anchor>, ...]` field at the relevant HEAD
          location, AND
     (ii) add a corresponding entry in `context:` with that anchor.

   What goes in a context block:
     - Hedging that carried meaning. "Doable, *but* a schema
       rethink" — the "but" signals "consider carefully" and
       should be preserved as the reason this option is not
       a free win.
     - Emphasis-via-repetition. If the source restates a point
       3× for pacing, that itself is a signal — note it.
     - Original phrasing where it's load-bearing for tone or
       precision (e.g., the user's actual words for a value
       judgment).
     - Motivating anecdotes / concrete grounding. The "why we
       care" story behind a decision, kept verbatim or near-
       verbatim.
     - Cross-version / historical context that explains how the
       current state came to be.

   What does NOT go in a context block:
     - Anything already captured in the HEAD. Context blocks
       must be additive, not duplicative.
     - Pure restatement / summary. If the block reads as "this
       is what was just said in the HEAD, in prose," delete it.
     - Author voice for its own sake. Preserve voice only when
       downstream consumers need to mirror it.

   Anchor naming convention: `c.<scope>.<topic>` where scope
   identifies the HEAD location (e.g. `c.1a.framing` for an
   anchor attached to option 1a; `c.item2.lean.rationale` for
   one attached to item2's lean section). Keep anchor slugs
   short and slug-cased.

   Each context entry should make explicit *what would be lost*
   if it were dropped. Use a brief tag like `lost_if_dropped:`
   or just write it into the block. This forces honest
   judgment about whether the entry is actually load-bearing.

4. Do NOT introduce new content. This is restructuring, not
   re-deliberation. If you spot a complication the source missed,
   note it in your final summary to the user — do not insert it
   into the AI-companion file. The two docs must agree on facts
   and conclusions. (Same rule applies to context blocks — they
   preserve source content, they don't add new commentary.)

5. Do NOT prettify or expand. No filler description. No "this
   document covers..." preamble. No closing summary. The first
   line of the file should be load-bearing.

6. Cross-references stay machine-resolvable. Replace prose like
   "as we discussed in the requirements doc" with a refs block
   entry and a slug reference (refs.spec).

7. After writing the file, give the user a brief report:
   - source token count vs output token count (rough estimate
     from word count is fine; don't run a tokenizer)
   - which schema you targeted and why; flag any place you had
     to use `extensions:` and what couldn't be expressed in the
     core (this is signal that the schema may need to evolve)
   - any content you found ambiguous in the source (where you
     had to make a compression judgment)
   - confirmation that all options / verdicts / open questions
     from the source survive
   - if lossless mode: how many context anchors you created and
     a one-line characterization of what each preserves (helps
     the user spot anchors that should have been merged or split)

   Keep the report under 200 words. The user needs to spot-check,
   not re-read.

Hard rules for this drafting task:

- Don't commit, don't push, don't open a PR. This produces a
  companion file, nothing else.
- Don't edit the source doc. If the source has an actual error,
  flag it in the report — fixing the source is a separate task.
- Don't touch implementation files, build configs, or any code
  that ships. This is a docs task only.
- Don't generate AI-rewrites for files that don't exist yet, or
  for drafts the user hasn't finished. Compress stable content
  only.
- Don't write multiple format variants ("here's a YAML version
  and here's a JSON version"). Pick one and commit. The user
  can ask for a different format if the choice is wrong.
```

## When this template fits vs. doesn't

**Fits:**
- Stable, high-traffic docs an agent will read repeatedly across
  long-context tasks (architecture references, finalized specs,
  decision-shaped deliberation docs, mature runbooks).
- Documents loaded by sub-agents at fan-out, where token cost
  multiplies per spawn.
- Long deliberation docs with parallel option structure — these
  compress especially well into uniform-shape YAML.
- Reference material that humans rarely re-read but agents do
  (e.g., a corner-case-heavy schema or API doc).

**Doesn't fit:**
- Drafts, personal notes, or anything you're still actively
  shaping. Compression pre-supposes the content is settled.
- Short docs (under ~500 words). The maintenance overhead of
  keeping two files in sync exceeds the per-read savings.
- Tutorial / onboarding content where narrative scaffolding *is*
  the value (the human reader needs the arc).
- Anything that exists primarily to be skimmed by a human in a
  PR review. Compress for agents only when agents are the actual
  bottleneck.
- Files under active multi-author collaboration. Drift between
  the human and AI versions becomes a coordination cost.
