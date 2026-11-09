// Form helpers for answering the CLI's pauses (aip docs/cli-json.md), mirroring how `aip run
// --interactive` reads them. Pure functions; the run view in views/Run.tsx uses them.
import type { DecisionQuestion } from "../api/console";

/** A form value as the typed JSON value an input of `type` expects (the CLI's `_coerce`). */
export function coerce(raw: string, type: string): unknown {
  const text = raw.trim();
  switch (type) {
    case "string": return raw;
    case "integer": {
      if (!/^-?\d+$/.test(text)) throw new Error(`expected an integer, got ${JSON.stringify(raw)}`);
      return Number(text);
    }
    case "float": {
      const n = Number(text);
      if (text === "" || Number.isNaN(n)) throw new Error(`expected a number, got ${JSON.stringify(raw)}`);
      return n;
    }
    case "boolean": {
      if (/^(true|yes|y|1)$/i.test(text)) return true;
      if (/^(false|no|n|0)$/i.test(text)) return false;
      throw new Error(`expected true or false, got ${JSON.stringify(raw)}`);
    }
    default:
      return JSON.parse(text);   // object, list[...]
  }
}

/** The empty value of a typed input, as text for a form field. */
export function blankFor(type: string): string {
  if (type === "object") return "{}";
  if (type.startsWith("list")) return "[]";
  return "";
}

/** A payload value as the text of a form field. */
export function asFieldText(value: unknown, type: string): string {
  if (value === undefined) return blankFor(type);
  if (type === "string" && typeof value === "string") return value;
  if (type === "boolean" || type === "integer" || type === "float") return String(value);
  return JSON.stringify(value);
}

/** [value, label] pairs for one decision question's radios. */
export function optionsOf(q: DecisionQuestion): [string, string][] {
  if (q.type === "noul") {
    const c = (q.criteria ?? {}) as Record<string, string | null>;
    return [["true", c.true ? `yes — ${c.true}` : "yes"], ["false", c.false ? `no — ${c.false}` : "no"]];
  }
  if (q.type === "choice") {
    return Object.entries((q.criteria ?? {}) as Record<string, string | null>).map(([label, d]) => [label, d ? `${label} — ${d}` : label]);
  }
  return ((q.criteria ?? []) as (string | null)[]).map((d, i) => [String(i), d ? `${i} — ${d}` : String(i)]);
}

/** A radio's value as the answer's JSON value: a noul's boolean, a score's level number, a choice's label. */
export function answerOf(type: DecisionQuestion["type"], value: string): boolean | string | number {
  return type === "noul" ? value === "true" : type === "score" ? Number(value) : value;
}
