#!/usr/bin/env python3
"""mapper.py — emit idempotent Cypher from a deliberation AI-rewrite.

Inputs:
  --schema   Path to the JSON Schema (e.g. deliberation.schema.json).
             Used for validation; the mapping logic is hardcoded for the
             deliberation schema.
  --rewrite  Path to the AI-rewrite YAML/markdown file (lossy mode only).
  --source   Path to the original markdown source. Becomes a
             :SourceDocument node carrying the full prose, so any consumer
             can fall back from the structured graph to the original
             context via a single relationship traversal.
  --out      Optional output path. Defaults to stdout.

Output:
  A Cypher script. All statements are idempotent (MERGE on stable ids);
  re-running with updated content upserts in place. Pipe the output to
  any Cypher runner — e.g.:

    uv run docs/workflow/mapper/mapper.py \
      --schema  docs/workflow/schemas/deliberation.schema.json \
      --rewrite docs/v0_3_1_introspect_dedup/ai-discussion.md \
      --source  docs/v0_3_1_introspect_dedup/discussion.md \
      | neo4j-cli query -

  (Run docs/workflow/schemas/deliberation.cypher once first to set up
  constraints and indexes.)

Design decisions:
  - Source MD becomes a node, not a property. Other rewrites can share
    the same source via MERGE on path; cross-doc :REFERENCES edges
    target source nodes (and seed stub source nodes when the referenced
    doc hasn't been ingested yet).
  - Structured cons (the map form, not the string-list form) get
    flattened into top-level keys for the .cons LIST<STRING> property,
    plus the full structure JSON-encoded into .cons_structured. Lossy
    in shape but lossless in content.
  - Lean.pick is stored as the raw string. A [:PICKS] edge is created
    only when the string resolves cleanly to a single option key or
    shape key. Composite picks (e.g. 'A (start with), 2e queued')
    leave the edge unset; the string remains queryable.
  - Shape.composition is parsed as `<key> + <key> + …` when possible,
    creating [:COMPOSES]->Option edges. Otherwise the raw string stays
    on the node.
  - Lossless mode is rejected up front. The context: TAIL has no graph
    representation in this version; lossless docs would need their own
    schema and mapper.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


# ─── parsing helpers ──────────────────────────────────────────────────

def parse_yaml_head(text: str) -> dict:
    """Strip optional --- frontmatter delimiters and parse body as YAML."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        body = parts[1] if len(parts) >= 2 else text
    else:
        body = text
    return yaml.safe_load(body)


def cy_str(s) -> str:
    """Quote a value for Cypher as a double-quoted string. Preserves
    newlines literally; escapes \\ and \"."""
    if s is None:
        return "NULL"
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def cy_list(xs) -> str:
    if not xs:
        return "[]"
    return "[" + ", ".join(cy_str(x) for x in xs) + "]"


def stable_id(*parts) -> str:
    return ":".join(str(p) for p in parts)


# ─── option/shape parsing ─────────────────────────────────────────────

def parse_pick(pick: str, option_keys: set, shape_keys: set):
    """Return ('option'|'shape', key) if pick is a single resolvable
    reference; None otherwise."""
    if pick is None:
        return None
    s = pick.strip()
    if s in option_keys:
        return ("option", s)
    if s in shape_keys:
        return ("shape", s)
    return None


def parse_composition(composition: str, option_keys: set):
    """Return list of option keys if composition is `<k> + <k> + …` and
    every key is known; otherwise None."""
    if composition is None:
        return None
    parts = [p.strip() for p in composition.split("+")]
    if not parts:
        return None
    if all(p in option_keys for p in parts):
        return parts
    return None


def cons_to_props(cons):
    """Return (cons_list, cons_structured_json|None)."""
    if cons is None:
        return ([], None)
    if isinstance(cons, list):
        # Flat string list — straightforward.
        return ([str(c) for c in cons], None)
    if isinstance(cons, dict):
        # Map form — flatten keys for .cons, keep full as JSON.
        return (list(cons.keys()), json.dumps(cons, ensure_ascii=False))
    # Fallback (shouldn't happen if schema validates).
    return ([str(cons)], None)


# ─── emitters ─────────────────────────────────────────────────────────

def emit_source_doc(source_path: Path, content: str) -> str:
    sha = hashlib.sha256(content.encode()).hexdigest()
    return f"""
// ─── Source document ───
MERGE (s:SourceDocument {{path: {cy_str(str(source_path))}}})
SET s.sha256     = {cy_str(sha)},
    s.content    = {cy_str(content)},
    s.indexed_at = datetime();
"""


def emit_ai_rewrite(doc: dict, source_path: Path, rewrite_path: Path) -> str:
    aid = doc["doc"]
    return f"""
// ─── AI-rewrite root + provenance edge to source ───
MERGE (a:AiRewrite {{id: {cy_str(aid)}}})
SET a.schema       = {cy_str(doc.get("schema"))},
    a.status       = {cy_str(doc.get("status"))},
    a.doc          = {cy_str(aid)},
    a.trigger      = {cy_str(doc.get("trigger"))},
    a.rewrite_path = {cy_str(str(rewrite_path))},
    a.indexed_at   = datetime();

MATCH (a:AiRewrite {{id: {cy_str(aid)}}}),
      (s:SourceDocument {{path: {cy_str(str(source_path))}}})
MERGE (a)-[:DERIVED_FROM]->(s);
"""


def emit_refs(doc: dict) -> str:
    aid = doc["doc"]
    refs = doc.get("refs") or {}
    out = ["\n// ─── Cross-doc references (slug → SourceDocument) ───"]
    for slug, path in refs.items():
        out.append(f"""
MERGE (s:SourceDocument {{path: {cy_str(path)}}});

MATCH (a:AiRewrite {{id: {cy_str(aid)}}}),
      (s:SourceDocument {{path: {cy_str(path)}}})
MERGE (a)-[r:REFERENCES {{slug: {cy_str(slug)}}}]->(s);""")
    return "\n".join(out)


def emit_glossary(doc: dict) -> str:
    aid = doc["doc"]
    glossary = doc.get("glossary") or {}
    out = ["\n// ─── Glossary terms ───"]
    for term, definition in glossary.items():
        gid = stable_id(aid, "glossary", term)
        defn = definition if isinstance(definition, str) else json.dumps(definition, ensure_ascii=False)
        out.append(f"""
MERGE (g:GlossaryTerm {{id: {cy_str(gid)}}})
SET g.term       = {cy_str(term)},
    g.definition = {cy_str(defn)};

MATCH (a:AiRewrite {{id: {cy_str(aid)}}}),
      (g:GlossaryTerm {{id: {cy_str(gid)}}})
MERGE (a)-[:DEFINES_TERM]->(g);""")
    return "\n".join(out)


def emit_item(aid: str, item_key: str, item: dict) -> str:
    iid = stable_id(aid, "item", item_key)
    option_keys = set((item.get("options") or {}).keys())
    shape_keys = set((item.get("shapes") or {}).keys())

    out = [f"""
// ─── Item: {item_key} ───
MERGE (i:Item {{id: {cy_str(iid)}}})
SET i.key     = {cy_str(item_key)},
    i.name    = {cy_str(item.get("name"))},
    i.problem = {cy_str(item.get("problem"))};

MATCH (a:AiRewrite {{id: {cy_str(aid)}}}),
      (i:Item {{id: {cy_str(iid)}}})
MERGE (a)-[:HAS_ITEM]->(i);"""]

    # today_behavior is a list of strings; store as a list property on Item
    # via SET (no separate node). Keeps the graph compact.
    today = item.get("today_behavior")
    if today:
        out.append(f"""
MATCH (i:Item {{id: {cy_str(iid)}}})
SET i.today_behavior = {cy_list(today)};""")

    # Options
    for opt_key, opt in (item.get("options") or {}).items():
        out.append(emit_option(iid, opt_key, opt))

    # Shapes
    for shape_key, shape in (item.get("shapes") or {}).items():
        out.append(emit_shape(iid, shape_key, shape, option_keys))

    # Lean
    if item.get("lean"):
        out.append(emit_lean(iid, item["lean"], option_keys, shape_keys))

    # Open questions
    for idx, oq in enumerate(item.get("open_questions") or []):
        out.append(emit_open_question(iid, idx, oq))

    return "\n".join(out)


def emit_option(iid: str, opt_key: str, opt: dict) -> str:
    oid = stable_id(iid, "option", opt_key)
    cons_list, cons_struct = cons_to_props(opt.get("cons"))

    set_clauses = [
        f"o.key            = {cy_str(opt_key)}",
        f"o.name           = {cy_str(opt.get('name'))}",
        f"o.action         = {cy_str(opt.get('action'))}",
        f"o.pros           = {cy_list(opt.get('pros') or [])}",
        f"o.cons           = {cy_list(cons_list)}",
        f"o.verdict        = {cy_str(opt.get('verdict'))}",
        f"o.verdict_reason = {cy_str(opt.get('verdict_reason'))}",
    ]
    if cons_struct is not None:
        set_clauses.append(f"o.cons_structured = {cy_str(cons_struct)}")
    for sketch in ("code_sketch", "cypher_sketch", "sql_sketch"):
        if opt.get(sketch):
            set_clauses.append(f"o.{sketch} = {cy_str(opt[sketch])}")

    return f"""
// ── Option: {opt_key} ──
MERGE (o:Option {{id: {cy_str(oid)}}})
SET {",\n    ".join(set_clauses)};

MATCH (i:Item {{id: {cy_str(iid)}}}),
      (o:Option {{id: {cy_str(oid)}}})
MERGE (i)-[:HAS_OPTION]->(o);"""


def emit_shape(iid: str, shape_key: str, shape: dict, option_keys: set) -> str:
    sid = stable_id(iid, "shape", shape_key)
    out = [f"""
// ── Shape: {shape_key} ──
MERGE (sh:Shape {{id: {cy_str(sid)}}})
SET sh.key         = {cy_str(shape_key)},
    sh.name        = {cy_str(shape.get("name"))},
    sh.composition = {cy_str(shape.get("composition"))},
    sh.intent      = {cy_str(shape.get("intent"))},
    sh.scope       = {cy_str(shape.get("scope"))},
    sh.requires    = {cy_list(shape.get("requires") or [])};

MATCH (i:Item {{id: {cy_str(iid)}}}),
      (sh:Shape {{id: {cy_str(sid)}}})
MERGE (i)-[:HAS_SHAPE]->(sh);"""]

    # If composition parses, create [:COMPOSES] edges
    composed = parse_composition(shape.get("composition"), option_keys)
    if composed:
        for opt_key in composed:
            oid = stable_id(iid, "option", opt_key)
            out.append(f"""
MATCH (sh:Shape {{id: {cy_str(sid)}}}),
      (o:Option {{id: {cy_str(oid)}}})
MERGE (sh)-[:COMPOSES]->(o);""")
    return "\n".join(out)


def emit_lean(iid: str, lean: dict, option_keys: set, shape_keys: set) -> str:
    lid = stable_id(iid, "lean")
    landing = lean.get("landing")
    out = [f"""
// ── Lean ──
MERGE (l:Lean {{id: {cy_str(lid)}}})
SET l.pick         = {cy_str(lean.get("pick"))},
    l.because      = {cy_str(lean.get("because"))},
    l.rationale    = {cy_str(lean.get("rationale"))},
    l.synergy_note = {cy_str(lean.get("synergy_note"))},
    l.landing      = {cy_str(json.dumps(landing, ensure_ascii=False) if landing is not None else None)};

MATCH (i:Item {{id: {cy_str(iid)}}}),
      (l:Lean {{id: {cy_str(lid)}}})
MERGE (i)-[:HAS_LEAN]->(l);"""]

    # If pick resolves cleanly, create [:PICKS] edge
    parsed = parse_pick(lean.get("pick"), option_keys, shape_keys)
    if parsed:
        kind, key = parsed
        if kind == "option":
            target_id = stable_id(iid, "option", key)
            out.append(f"""
MATCH (l:Lean {{id: {cy_str(lid)}}}),
      (o:Option {{id: {cy_str(target_id)}}})
MERGE (l)-[:PICKS]->(o);""")
        else:  # shape
            target_id = stable_id(iid, "shape", key)
            out.append(f"""
MATCH (l:Lean {{id: {cy_str(lid)}}}),
      (sh:Shape {{id: {cy_str(target_id)}}})
MERGE (l)-[:PICKS]->(sh);""")
    return "\n".join(out)


def emit_open_question(iid: str, idx: int, oq: dict) -> str:
    qid = stable_id(iid, "openq", idx)
    return f"""
// ── Open question #{idx} ──
MERGE (q:OpenQuestion {{id: {cy_str(qid)}}})
SET q.q          = {cy_str(oq.get("q"))},
    q.answer     = {cy_str(oq.get("answer"))},
    q.likely     = {cy_str(oq.get("likely"))},
    q.belongs_to = {cy_str(oq.get("belongs_to"))};

MATCH (i:Item {{id: {cy_str(iid)}}}),
      (q:OpenQuestion {{id: {cy_str(qid)}}})
MERGE (i)-[:HAS_OPEN_QUESTION]->(q);"""


def emit_interaction(doc: dict) -> str:
    aid = doc["doc"]
    inter = doc.get("interaction")
    if not inter:
        return ""
    xid = stable_id(aid, "interaction")
    return f"""
// ─── Interaction (cross-item) ───
MERGE (x:Interaction {{id: {cy_str(xid)}}})
SET x.conflict = {cy_str(inter.get("conflict"))},
    x.synergy  = {cy_str(inter.get("synergy"))};

MATCH (a:AiRewrite {{id: {cy_str(aid)}}}),
      (x:Interaction {{id: {cy_str(xid)}}})
MERGE (a)-[:HAS_INTERACTION]->(x);"""


def emit_ordering(doc: dict) -> str:
    aid = doc["doc"]
    ordering = doc.get("ordering")
    if not ordering:
        return ""
    oid = stable_id(aid, "ordering")
    return f"""
// ─── Ordering (release sequencing) ───
MERGE (o:Ordering {{id: {cy_str(oid)}}})
SET o.payload = {cy_str(json.dumps(ordering, ensure_ascii=False))};

MATCH (a:AiRewrite {{id: {cy_str(aid)}}}),
      (o:Ordering {{id: {cy_str(oid)}}})
MERGE (a)-[:HAS_ORDERING]->(o);"""


# ─── main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Emit idempotent Cypher from a deliberation AI-rewrite."
    )
    ap.add_argument("--schema", required=True, type=Path,
                    help="JSON Schema (must be deliberation.schema.json)")
    ap.add_argument("--rewrite", required=True, type=Path,
                    help="AI-rewrite YAML/markdown (lossy mode only)")
    ap.add_argument("--source", required=True, type=Path,
                    help="Original markdown source")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output path (default: stdout)")
    args = ap.parse_args()

    schema = json.loads(args.schema.read_text())
    rewrite_text = args.rewrite.read_text()
    source_text = args.source.read_text()
    doc = parse_yaml_head(rewrite_text)

    if doc is None:
        print(f"ERROR: could not parse YAML from {args.rewrite}", file=sys.stderr)
        sys.exit(2)

    # Validate against schema
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        for e in errors:
            path = "/".join(str(p) for p in e.absolute_path) or "<root>"
            print(f"SCHEMA ERROR at {path}: {e.message}", file=sys.stderr)
        sys.exit(2)

    # This mapper is deliberation-specific
    if doc.get("schema") != "deliberation":
        print(
            f"ERROR: this mapper only handles schema='deliberation'; "
            f"got schema={doc.get('schema')!r}",
            file=sys.stderr,
        )
        sys.exit(3)

    # Lossy only
    if doc.get("mode") == "lossless":
        print(
            "ERROR: this mapper only handles lossy AI-rewrites; "
            "got mode=lossless. Lossless docs would need their own schema "
            "and mapper to represent the context: TAIL.",
            file=sys.stderr,
        )
        sys.exit(3)

    # Emit
    parts = [
        "// ════════════════════════════════════════════════════════════",
        "// Generated by docs/workflow/mapper/mapper.py",
        f"// Source:    {args.source}",
        f"// Rewrite:   {args.rewrite}",
        f"// Schema:    {args.schema}",
        "// Idempotent: all statements use MERGE on stable ids; safe to re-run.",
        "// Prerequisite: docs/workflow/schemas/deliberation.cypher must be",
        "//               applied first to set up constraints/indexes.",
        "// ════════════════════════════════════════════════════════════",
        emit_source_doc(args.source, source_text),
        emit_ai_rewrite(doc, args.source, args.rewrite),
        emit_refs(doc),
        emit_glossary(doc),
    ]
    for item_key, item in (doc.get("items") or {}).items():
        parts.append(emit_item(doc["doc"], item_key, item))
    parts.append(emit_interaction(doc))
    parts.append(emit_ordering(doc))

    output = "\n".join(p for p in parts if p)
    if args.out:
        args.out.write_text(output)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
