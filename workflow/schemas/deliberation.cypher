// deliberation.cypher
//
// Current-day, executable equivalent of deliberation.gql.
// Run once per Neo4j database (instance + dbname) before invoking the
// mapper. All statements are idempotent (IF NOT EXISTS); safe to re-run.
//
//   neo4j-cli query --file docs/workflow/schemas/deliberation.cypher
//
// When Neo4j's CREATE GRAPH TYPE feature is GA, replace this file with
// the .gql declaration and a single CREATE GRAPH TYPE invocation.

// === Uniqueness constraints (canonical ids) ===

CREATE CONSTRAINT source_document_path IF NOT EXISTS
  FOR (s:SourceDocument) REQUIRE s.path IS UNIQUE;

CREATE CONSTRAINT ai_rewrite_id IF NOT EXISTS
  FOR (a:AiRewrite) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT item_id IF NOT EXISTS
  FOR (i:Item) REQUIRE i.id IS UNIQUE;

CREATE CONSTRAINT option_id IF NOT EXISTS
  FOR (o:Option) REQUIRE o.id IS UNIQUE;

CREATE CONSTRAINT lean_id IF NOT EXISTS
  FOR (l:Lean) REQUIRE l.id IS UNIQUE;

CREATE CONSTRAINT shape_id IF NOT EXISTS
  FOR (sh:Shape) REQUIRE sh.id IS UNIQUE;

CREATE CONSTRAINT open_question_id IF NOT EXISTS
  FOR (q:OpenQuestion) REQUIRE q.id IS UNIQUE;

CREATE CONSTRAINT glossary_term_id IF NOT EXISTS
  FOR (g:GlossaryTerm) REQUIRE g.id IS UNIQUE;

CREATE CONSTRAINT interaction_id IF NOT EXISTS
  FOR (x:Interaction) REQUIRE x.id IS UNIQUE;

CREATE CONSTRAINT ordering_id IF NOT EXISTS
  FOR (o:Ordering) REQUIRE o.id IS UNIQUE;

// === Indexes for common query patterns ===

CREATE INDEX ai_rewrite_status IF NOT EXISTS
  FOR (a:AiRewrite) ON (a.status);

CREATE INDEX ai_rewrite_schema IF NOT EXISTS
  FOR (a:AiRewrite) ON (a.schema);

CREATE INDEX option_verdict IF NOT EXISTS
  FOR (o:Option) ON (o.verdict);

CREATE INDEX item_name IF NOT EXISTS
  FOR (i:Item) ON (i.name);

CREATE INDEX option_name IF NOT EXISTS
  FOR (o:Option) ON (o.name);

// === Fulltext index on source content ===
// Lets agents fall back to the full prose when the structured data
// isn't enough (the reason we ingest the original MD as a node).

CREATE FULLTEXT INDEX source_document_content IF NOT EXISTS
  FOR (s:SourceDocument) ON EACH [s.content];
