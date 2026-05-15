# Mapper — AI-rewrite YAML → Neo4j graph

`mapper.py` ingests a deliberation AI-rewrite (validated against
`docs/workflow/schemas/deliberation.schema.json`) and emits idempotent
Cypher that materializes its content as a Neo4j graph. The original
markdown source becomes a `:SourceDocument` node carrying the full
prose, so any consumer can fall back from the structured graph to the
original context via a single relationship traversal.

## Why ingest into Neo4j

The schema-validated YAML is already machine-tractable. Putting it in a
graph adds three things:

1. **Cross-doc queries become trivial.** "Every option rejected for
   `speculative` reasons across all deliberations," "every shape that
   composes option 2e," "every open question still tagged
   `belongs_to: spec-time`." One Cypher query each.
2. **Cross-doc links become first-class.** The `refs:` map in each YAML
   becomes `[:REFERENCES]` edges to other `:SourceDocument` nodes.
   Stubs are created for unindexed referenced docs and upgraded in place
   when those docs are later ingested. This is the seed of the
   process-knowledge-graph idea in `ai-rewrite.md`.
3. **Original context stays one hop away.** The `:SourceDocument` node
   carries the full markdown (with a `FULLTEXT INDEX` on `content`), so
   agents can drop from "structured decision" to "full motivating prose"
   without a separate file fetch.

## Pipeline

```
  human-prose source            AI-rewrite YAML (lossy mode)
  (e.g. discussion.md)          (e.g. ai-discussion.md)
           │                              │
           │                              │
           └──────────────┬───────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │       mapper.py        │
              │  - validates YAML      │
              │    against JSON Schema │
              │  - rejects lossless    │
              │  - emits Cypher        │
              └────────────────────────┘
                          │
                          ▼
                  Cypher script
                          │
                          ▼  (one-time, before first ingest:
                          │   apply deliberation.cypher to set up
                          │   constraints + indexes)
                          ▼
                       Neo4j
```

## Usage

One-time setup per database — apply constraints and indexes:

```bash
neo4j-cli query --file docs/workflow/schemas/deliberation.cypher
```

Per-doc ingest:

```bash
uv run --with pyyaml --with jsonschema python3 docs/workflow/mapper/mapper.py \
  --schema  docs/workflow/schemas/deliberation.schema.json \
  --rewrite docs/v0_3_1_introspect_dedup/ai-discussion.md \
  --source  docs/v0_3_1_introspect_dedup/discussion.md \
  --out     /tmp/v0.3.1.cypher

neo4j-cli query --file /tmp/v0.3.1.cypher
```

Or pipe directly:

```bash
uv run ... mapper.py --schema ... --rewrite ... --source ... | neo4j-cli query -
```

The mapper is deliberately stdout-by-default so you can inspect the
generated Cypher before applying it.

## Idempotency

Every node uses `MERGE` on a stable id. Re-running the same inputs
produces the same graph; running with updated content upserts in place.
Stable id scheme:

| Node            | id format                                       |
|-----------------|-------------------------------------------------|
| SourceDocument  | `<repo-relative path>`                          |
| AiRewrite       | `<doc.doc>` (e.g. `v0.3.1-discussion`)          |
| Item            | `<ai-rewrite-id>:item:<key>`                    |
| Option          | `<item-id>:option:<key>`                        |
| Lean            | `<item-id>:lean`                                |
| Shape           | `<item-id>:shape:<key>`                         |
| OpenQuestion    | `<item-id>:openq:<index>`                       |
| GlossaryTerm    | `<ai-rewrite-id>:glossary:<term>`               |
| Interaction     | `<ai-rewrite-id>:interaction`                   |
| Ordering        | `<ai-rewrite-id>:ordering`                      |

Re-ordering open questions in the source YAML will renumber them and
create new nodes; old ones go orphan. If question stability across edits
matters, add a stable `id:` field to the `open_question` schema and key
on that instead. (Out of scope for v1.)

## Graph shape

See `docs/workflow/schemas/deliberation.gql` for the forward-looking
declarative graph type, and `docs/workflow/schemas/deliberation.cypher`
for the current-day constraints. Headline structure:

```
(SourceDocument) <-[:DERIVED_FROM]- (AiRewrite) -[:HAS_ITEM]-> (Item)
                                       │                          │
                                       │                          ├-[:HAS_OPTION]-> (Option)
                                       │                          ├-[:HAS_SHAPE]--> (Shape) -[:COMPOSES]-> (Option)
                                       │                          ├-[:HAS_LEAN]---> (Lean)  -[:PICKS]----> (Option | Shape)
                                       │                          └-[:HAS_OPEN_QUESTION]-> (OpenQuestion)
                                       │
                                       ├-[:DEFINES_TERM]-> (GlossaryTerm)
                                       ├-[:HAS_INTERACTION]-> (Interaction)
                                       ├-[:HAS_ORDERING]----> (Ordering)
                                       │
                                       └-[:REFERENCES {slug}]-> (SourceDocument)   ← cross-doc links
```

## Example queries (once ingested)

```cypher
// Every rejected option across all deliberations, with reason
MATCH (o:Option {verdict: 'rejected'})<-[:HAS_OPTION]-(i:Item)<-[:HAS_ITEM]-(a:AiRewrite)
RETURN a.id AS deliberation, i.name AS item, o.key AS option,
       o.verdict_reason AS reason
ORDER BY a.id, i.name, o.key;

// Every open question that blocks a spec
MATCH (q:OpenQuestion)<-[:HAS_OPEN_QUESTION]-(i:Item)<-[:HAS_ITEM]-(a:AiRewrite)
WHERE q.belongs_to CONTAINS 'spec'
RETURN a.id AS deliberation, i.name AS item, q.q AS question;

// Cross-doc references — what does this deliberation point at?
MATCH (a:AiRewrite {id: 'v0.3.1-discussion'})-[r:REFERENCES]->(s:SourceDocument)
RETURN r.slug AS slug, s.path AS path;

// Pull full source prose for a deliberation (the context-fallback path)
MATCH (a:AiRewrite {id: 'v0.3.1-discussion'})-[:DERIVED_FROM]->(s:SourceDocument)
RETURN s.content;

// Find every option a given shape composes
MATCH (sh:Shape)-[:COMPOSES]->(o:Option)
WHERE sh.id = 'v0.3.1-discussion:item:item2:shape:B'
RETURN o.key, o.name;
```

## Limitations / known behavior

- **Lossy mode only.** Lossless rewrites carry a `context:` TAIL with
  anchor refs from the HEAD; this mapper has no graph representation
  for that. Lossless ingestion would need its own schema and mapper.
- **Composite picks don't get [:PICKS] edges.** When `lean.pick` is a
  string like `"A (start with), 2e queued"` (not a single key), the
  raw string is preserved on `Lean.pick` but no `[:PICKS]` edge is
  created. Same logic for `shape.composition` that doesn't parse as a
  clean `<key> + <key> + …` list.
- **Structured cons.** When `cons:` is a map (rich nested concerns
  rather than a flat list), the top-level keys go into `Option.cons`
  (LIST<STRING>) for queryability, and the full map is JSON-serialized
  into `Option.cons_structured` (STRING) for losslessness. Future:
  break into `:Concern` nodes if cross-doc concern-mining justifies it.
- **`ordering:` is JSON-blob today.** The schema leaves `ordering`
  loosely structured; the mapper stores the whole map as JSON in
  `Ordering.payload`. Tighten when ordering shape stabilizes.
- **No deletions.** This mapper only writes. If a deliberation is
  archived or re-scoped, its old nodes need to be dropped manually
  (or by a future `--prune` mode that diffs current YAML against
  graph state).

## Future direction

When sibling schemas (`spec`, `release`, `incident`) gain mappers, the
graph becomes a queryable map of organizational reasoning across the
full dev lifecycle. Expected new edges:

- `(:Spec)-[:DERIVED_FROM_DELIBERATION]->(:AiRewrite)`
- `(:Release)-[:IMPLEMENTS_SPEC]->(:Spec)`
- `(:Incident)-[:REGRESSES_RELEASE]->(:Release)`

Adding a new doc-type mapper: scaffold it next to this one (e.g.
`spec_mapper.py`), wire it to the corresponding schema, and add the
new node + edge declarations to `deliberation.gql` (or a new
`spec.gql`) and `deliberation.cypher`.
