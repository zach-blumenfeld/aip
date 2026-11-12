// What a form field holds, as the JSON value the CLI expects for a key of that type: the inputs of
// `aip run --inputs` and the answers of `aip resume --answers` (aip docs/cli-json.md). No imports and
// no DOM: it runs under node as it is (test/answers.test.ts).

import type { Task } from "../api/types.ts";

/** How a key of `type` is asked for: one of a few values, a line of text, or JSON. */
export function fieldKind(type: string | null | undefined, labels?: string[]): "pick" | "text" | "number" | "json" {
  if (type === "true_or_false" || type === "boolean" || (labels && labels.length > 0)) return "pick";
  if (type === "string") return "text";
  if (type === "integer" || type === "float" || type === "number") return "number";
  return "json";
}

/** The values a `pick` field offers. */
export function optionsOf(type: string | null | undefined, labels?: string[]): string[] {
  return labels && labels.length > 0 ? labels : type === "true_or_false" || type === "boolean" ? ["true", "false"] : [];
}

/** A field's text as the value of a key of `type`; throws with what is wrong. */
export function coerce(raw: string | undefined, type: string | null | undefined, labels?: string[]): unknown {
  const text = (raw ?? "").trim();
  switch (fieldKind(type, labels)) {
    case "pick":
      if (text === "") throw new Error("pick one");
      if (labels && labels.length > 0) {
        if (!labels.includes(text)) throw new Error(`one of ${labels.join(", ")}`);
        return text;
      }
      return text === "true";
    case "text":
      return raw ?? "";
    case "number": {
      const n = Number(text);
      if (text === "" || Number.isNaN(n)) throw new Error(`expected a number, got ${JSON.stringify(raw ?? "")}`);
      if (type === "integer" && !Number.isInteger(n)) throw new Error(`expected a whole number, got ${text}`);
      return n;
    }
    default:
      if (text === "") throw new Error("expected JSON");
      try { return JSON.parse(text); } catch { throw new Error(`not JSON: ${text.slice(0, 40)}`); }
  }
}

/** A value as a field's text: the opposite of `coerce`, for a form's first state. */
export function fieldText(value: unknown, type: string | null | undefined): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string" && fieldKind(type) !== "json") return value.startsWith("<") && value.endsWith(">") ? "" : value;
  if (typeof value === "string") return JSON.stringify(value);
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** The fields of a form by key, typed: an object for the CLI, or the keys that would not go and why. */
export function collect(fields: Record<string, string>, types: Record<string, string | null>, labels: Record<string, string[]> = {}):
    { value: Record<string, unknown>; problems: Record<string, string> } {
  const value: Record<string, unknown> = {};
  const problems: Record<string, string> = {};
  for (const [key, type] of Object.entries(types)) {
    try { value[key] = coerce(fields[key], type, labels[key]); } catch (e) { problems[key] = e instanceof Error ? e.message : String(e); }
  }
  return { value, problems };
}

/** A pause's answer: the one task's object, or every task's keyed by its index (`{"0": {...}, "1": {...}}`),
 *  which is how several tasks at once are answered. */
export function answersFor(tasks: Task[], byTask: Record<number, Record<string, unknown>>): unknown {
  if (tasks.length === 1) return byTask[tasks[0].index] ?? {};
  return Object.fromEntries(tasks.map((t) => [String(t.index), byTask[t.index] ?? {}]));
}

/** The rows a `list` answer is picked from, when the task carries them: the one list in the state it reads (as
 *  make_procedure's `approve` reads `folders`). Null when there is none, or more than one to choose between. */
export function candidatesOf(type: string | null | undefined, state: Record<string, unknown>): unknown[] | null {
  if (type !== "list" && type !== "array") return null;
  const lists = Object.values(state).filter((v) => Array.isArray(v) && v.length > 0) as unknown[][];
  return lists.length === 1 ? lists[0] : null;
}

/** A row of a checklist in words: a string as it is, an object by its name, path or title, else as JSON. */
export function rowText(row: unknown): string {
  if (typeof row === "string") return row;
  if (row && typeof row === "object") {
    const o = row as Record<string, unknown>;
    for (const k of ["name", "path", "title", "id"]) if (typeof o[k] === "string") return o[k] as string;
  }
  return JSON.stringify(row);
}

/** `revise 1 / review 0`: every enclosing loop and which pass of it; empty outside loops. */
export function passLabel(passes: { loop: string; pass: number }[] | undefined): string {
  return (passes ?? []).map((p) => `${p.loop} ${p.pass}`).join(" / ");
}
