// Re-export an imported skill without reformatting it: the new values are written into the original YAML text,
// replacing only the scalars that changed, so blank lines, comments, quoting and folded prose stay as they were
// and a one-field edit is a one-line diff. Anything else (a key or list item added, removed or reordered) is a
// structural change, and the caller writes the YAML afresh instead.

import { isMap, isScalar, isSeq, parse, parseDocument, stringify, type Node } from "yaml";

interface Edit { start: number; end: number; text: string }

/** `src` (one YAML document) with its values changed to `value`, or null when that takes more than replacing
 *  scalars, or when the result would not parse back to `value`. */
export function patchYaml(src: string, value: unknown): string | null {
  const doc = parseDocument(src);
  if (doc.errors.length || !doc.contents) return null;
  const edits: Edit[] = [];
  if (!collect(src, doc.contents as Node, value, edits)) return null;
  let out = src;
  for (const e of edits.sort((a, b) => b.start - a.start)) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  try {
    return equal(parse(out), value) ? out : null;
  } catch {
    return null;
  }
}

function collect(src: string, node: Node | null, value: unknown, edits: Edit[]): boolean {
  if (node === null) return value === null || value === undefined;
  if (isScalar(node)) {
    if (equal(node.value, value)) return true;
    if (value !== null && typeof value === "object") return false;
    const [start, end] = node.range!;
    let text = scalar(value, node.type);
    if (src.slice(start, end).endsWith("\n")) text += "\n";   // a block scalar's range takes its line break
    edits.push({ start, end, text });
    return true;
  }
  if (isMap(node)) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
    const obj = value as Record<string, unknown>;
    const keys = node.items.map((p) => (isScalar(p.key) ? String(p.key.value) : null));
    if (keys.some((k) => k === null) || keys.length !== Object.keys(obj).length || keys.some((k) => !(k! in obj))) return false;
    return node.items.every((p, i) => collect(src, p.value as Node | null, obj[keys[i]!], edits));
  }
  if (isSeq(node)) {
    if (!Array.isArray(value) || value.length !== node.items.length) return false;
    return node.items.every((n, i) => collect(src, n as Node | null, value[i], edits));
  }
  return false;   // an alias, or anything else this does not rewrite
}

/** One value as an inline YAML scalar, quoted the way the old one was: a string with a line break is written
 *  double-quoted on one line, so it fits wherever the old scalar sat, whatever its indent. */
function scalar(value: unknown, style: string | undefined): string {
  if (typeof value === "string" && (value.includes("\n") || style === "QUOTE_DOUBLE")) return JSON.stringify(value);
  if (typeof value === "string" && style === "QUOTE_SINGLE") return `'${value.replace(/'/g, "''")}'`;
  return stringify(value, { lineWidth: 0 }).replace(/\n$/, "");
}

function equal(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) return a.length === (b as unknown[]).length && a.every((x, i) => equal(x, (b as unknown[])[i]));
  const ka = Object.keys(a), kb = Object.keys(b);
  return ka.length === kb.length && ka.every((k) => k in b && equal((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]));
}
