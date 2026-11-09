// The checks an agent's fill-in must pass before Accept (S6a), all programmatic; the agent's own word counts for
// nothing. In order:
//   1. `aip-spec validate` on the result, in the console's process. Without aip-spec the checks refuse to run: the
//      TypeScript linter is not a substitute.
//   2. Adherence: the result's SKILL.md says what the Draft says on everything frozen. An empty prose field the agent
//      filled is allowed and listed for review; `requires` lists the agent only added to are flagged, not failed.
//   3. Script contract: every execution step's script, run with synthetic inputs of the declared types (outputs fed
//      forward along the graph), prints one JSON object holding exactly the declared outputs, with their types.
//      Every template's `{key}` fields resolve against the step's inputs and assets.
//   4. Completeness: no placeholder marker anywhere, no `unfinished` lint issue, no file the graph names empty or
//      only comments.
// A result is accepted only when every check passes (the definition of done in docs/plans/STUDIO-PLAN.md).

import type { ZipFile } from "../zip";
import { CONFIDENCE_TYPE, QUESTION_TYPES, confidenceKey, startOf, type Draft, type Step } from "./draft";
import { lint, PLACEHOLDER_MARKER } from "./lint";
import { skillMdToDraft } from "./serialize";
import { NOTES_PATH, README_PATH, STUDIO_NOTE } from "./scaffold";

export type CheckName = "validate" | "adherence" | "contract" | "completeness";

export interface CheckResult {
  name: CheckName;
  ok: boolean;
  /** Each failure, naming the step, field or file. */
  failures: string[];
}

export interface Fill { label: string; value: string }

export interface Verdict {
  /** Set when the checks could not run at all (no aip-spec, the result is not a skill). Accept stays disabled. */
  refused?: string;
  checks: CheckResult[];
  /** Empty prose fields the agent wrote, for review. */
  filled: Fill[];
  /** What the user should look at before accepting (packages the agent added to `requires`). */
  flags: string[];
  /** The result as a Draft, when its SKILL.md parsed. */
  result?: Draft;
  /** True only when every check passed. */
  ok: boolean;
}

/** What runs in the console's process: the validator and one script. */
export interface Runner {
  validate(name: string, files: ZipFile[]): Promise<{ valid: boolean; issues: { kind: string; message: string; severity?: string; path?: string }[] }>;
  probe(name: string, files: ZipFile[], script: string, stdin: unknown, timeout?: number): Promise<{ code: number | null; stdout?: string; stderr?: string; timedOut?: boolean; error?: string }>;
}

/** The runner's way of saying aip-spec is not installed: the checks refuse instead of failing. */
export class MissingValidator extends Error {}

const decoder = new TextDecoder();
const textOf = (f: ZipFile) => decoder.decode(f.bytes);

export async function checkResult(draft: Draft, files: ZipFile[], runner: Runner): Promise<Verdict> {
  const md = files.find((f) => f.path === "SKILL.md");
  if (!md) return refuse("the result has no SKILL.md");
  let result: Draft;
  try {
    result = skillMdToDraft(textOf(md));
  } catch (e) {
    return refuse(`the result's SKILL.md does not parse: ${e instanceof Error ? e.message : String(e)}`);
  }

  let validate: CheckResult;
  try {
    const v = await runner.validate(result.name || draft.name, files);
    const errors = v.issues.filter((i) => i.severity !== "warning");
    validate = { name: "validate", ok: v.valid && errors.length === 0, failures: errors.map((i) => `${i.path ? `${i.path}: ` : ""}${i.message} (${i.kind})`) };
    if (!validate.ok && validate.failures.length === 0) validate.failures.push("aip-spec validate rejected the result");
  } catch (e) {
    if (e instanceof MissingValidator) return { ...refuse(e.message), result };
    throw e;
  }

  const a = adherence(draft, result);
  const contract = await scriptContract(result, files, runner);
  const complete = completeness(result, files);
  const checks = [validate, { name: "adherence" as const, ok: a.failures.length === 0, failures: a.failures }, contract, complete];
  return { checks, filled: a.filled, flags: a.flags, result, ok: checks.every((c) => c.ok) };
}

function refuse(message: string): Verdict {
  return { refused: message, checks: [], filled: [], flags: [], ok: false };
}

// ------------------------------------------------------------------------------------------------ adherence

interface Fact { label: string; value: string; prose: boolean }

const show = (v: string) => (v === "" ? "(empty)" : `\`${v}\``);

/** Everything a Draft says, flattened to labelled values. Prose facts may be filled when empty and are frozen once
 *  written; the rest is frozen outright. `requires` is left out (adherence compares it on its own). */
export function facts(d: Draft): Map<string, Fact> {
  const m = new Map<string, Fact>();
  const put = (key: string, label: string, value: unknown, prose = false) => {
    m.set(key, { label, value: typeof value === "string" ? value : JSON.stringify(value ?? null), prose });
  };
  const nameOf = new Map(d.steps.map((s) => [s.id, s.name]));
  const target = (id: string | undefined) => (id === undefined ? null : nameOf.get(id) ?? id.replace(/^unresolved:/, ""));

  put("name", "the skill's `name`", d.name);
  put("description", "the skill's `description`", d.description, true);
  put("compatibility", "`compatibility`", d.compatibility ?? null);
  put("license", "`license`", d.license ?? null);
  put("allowedTools", "`allowed-tools`", d.allowedTools ?? null);
  put("metadata", "`metadata`", d.metadata ?? {});
  put("purpose", "`purpose`", d.purpose, true);
  put("triggerWhen", "the number of `trigger_when` entries", d.triggerWhen.length);
  d.triggerWhen.forEach((t, i) => put(`triggerWhen[${i}]`, `\`trigger_when\` entry ${i + 1}`, t, true));
  put("doNotUseWhen", "`do_not_use_when`", d.doNotUseWhen);
  put("antiPatterns", "`anti_patterns`", d.antiPatterns);
  put("steps", "the number of steps", d.steps.length);

  d.steps.forEach((s, n) => {
    const k = `steps[${n}]`;
    const at = `step ${n + 1} (\`${s.name}\`)`;
    put(`${k}.name`, `${at}: the name`, s.name);
    put(`${k}.kind`, `${at}: the kind`, s.kind);
    put(`${k}.description`, `${at}: the description`, s.description, true);
    const io = (which: "inputs" | "outputs", items: Step["inputs"]) => {
      put(`${k}.${which}`, `${at}: the number of ${which}`, items.length);
      items.forEach((it, i) => {
        put(`${k}.${which}[${i}].name`, `${at}: ${which} ${i + 1}'s name`, it.name);
        put(`${k}.${which}[${i}].type`, `${at}: ${which} \`${it.name}\`'s type`, it.type);
        put(`${k}.${which}[${i}].description`, `${at}: ${which} \`${it.name}\`'s description`, it.description ?? "");
      });
    };
    if (s.kind === "router") {
      put(`${k}.branchOn`, `${at}: \`branch_on\``, s.branchOn ?? "");
      put(`${k}.check`, `${at}: the confidence check`, s.check ? { key: s.check.key, below: s.check.below ?? null, to: target(s.check.to) } : null);
      put(`${k}.branches`, `${at}: the branches`, (s.branches ?? []).map((b) => [b.value, target(b.target)]));
      return;
    }
    io("inputs", s.inputs);
    if (s.kind !== "end") put(`${k}.next`, `${at}: the next step (\`inputs_to\`)`, target(s.next));
    if (s.kind === "decision") {
      const qs = s.questions ?? [];
      put(`${k}.questions`, `${at}: the questions`, qs.map((q) => [q.name, q.type]));
      qs.forEach((q, i) => {
        const qk = `${k}.questions[${i}]`;
        const qa = `${at}: question \`${q.name}\``;
        put(`${qk}.instructions`, `${qa}'s instructions`, q.instructions, true);
        if (q.type === "noul") {
          put(`${qk}.criteria.true`, `${qa}'s criterion for true`, q.criteria?.true ?? "", true);
          put(`${qk}.criteria.false`, `${qa}'s criterion for false`, q.criteria?.false ?? "", true);
        } else if (q.type === "choice") {
          put(`${qk}.labels`, `${qa}'s labels`, q.criteria.map((c) => c.label));
          q.criteria.forEach((c, j) => put(`${qk}.criteria[${j}]`, `${qa}'s description of \`${c.label}\``, c.description ?? "", true));
        } else {
          put(`${qk}.levels`, `${qa}'s number of levels`, q.criteria.length);
          q.criteria.forEach((c, j) => put(`${qk}.criteria[${j}]`, `${qa}'s level ${j}`, c, true));
        }
      });
      put(`${k}.confidence`, `${at}: the \`confidence\` list`, s.confidence ?? []);
      put(`${k}.fallback`, `${at}: \`fallback\``, !!s.fallback);
      put(`${k}.history`, `${at}: \`history\``, !!s.history);
    }
    if (s.kind === "execution" || s.kind === "client_task") {
      io("outputs", s.outputs ?? []);
      put(`${k}.assets`, `${at}: the assets`, s.assets ?? []);
    }
    if (s.kind === "execution") {
      put(`${k}.script`, `${at}: the script`, s.script ?? "");
      put(`${k}.command`, `${at}: the command`, s.command ?? null);
      put(`${k}.timeout`, `${at}: the timeout`, s.timeout ?? null);
    }
    if (s.kind === "client_task") {
      put(`${k}.template`, `${at}: the template`, s.template ?? "");
      put(`${k}.framing`, `${at}: \`framing\``, s.framing !== false);
      const refs = s.references ?? [];
      put(`${k}.references`, `${at}: the reference paths`, refs.map((r) => r.path));
      refs.forEach((r, i) => put(`${k}.references[${i}].description`, `${at}: reference \`${r.path}\`'s description`, r.description));
    }
  });
  return m;
}

/** The prose fields the Draft leaves empty: what the agent is asked to write. */
export function emptyProse(d: Draft): string[] {
  return [...facts(d).values()].filter((f) => f.prose && !f.value.trim()).map((f) => f.label);
}

export function adherence(draft: Draft, result: Draft): { failures: string[]; filled: Fill[]; flags: string[] } {
  const want = facts(draft), got = facts(result);
  const failures: string[] = [], filled: Fill[] = [], flags: string[] = [];
  for (const [key, w] of want) {
    const g = got.get(key);
    if (!g) { failures.push(`${w.label} is missing from the result`); continue; }
    if (g.value === w.value) continue;
    if (w.prose && !w.value.trim() && g.value.trim()) { filled.push({ label: w.label, value: g.value }); continue; }
    failures.push(`${w.label} changed: the draft has ${show(w.value)}, the result has ${show(g.value)}`);
  }
  for (const [key, g] of got) if (!want.has(key)) failures.push(`the result adds ${g.label} (${show(g.value)}), which the draft does not have`);

  // `requires` is frozen, except that lists the Draft left empty may gain entries, for the user to look at.
  const r = draft.requires, q = result.requires;
  if (!r && q) flags.push(`the agent added a \`requires\` block: ${JSON.stringify(q)}`);
  else if (r && !q) failures.push("the result drops the `requires` block");
  else if (r && q) {
    if (r.interpreter.name !== q.interpreter.name || (r.interpreter.version ?? "") !== (q.interpreter.version ?? "")) {
      failures.push(`\`requires.interpreter\` changed: the draft has \`${r.interpreter.name} ${r.interpreter.version ?? ""}\`, the result has \`${q.interpreter.name} ${q.interpreter.version ?? ""}\``);
    }
    for (const list of ["packages", "tools"] as const) {
      if (JSON.stringify(r[list]) === JSON.stringify(q[list])) continue;
      if (r[list].length === 0) flags.push(`the agent added to \`requires.${list}\`: ${q[list].join(", ")}`);
      else failures.push(`\`requires.${list}\` changed: the draft has ${r[list].join(", ") || "(none)"}, the result has ${q[list].join(", ") || "(none)"}`);
    }
  }
  return { failures, filled, flags };
}

// ------------------------------------------------------------------------------------------- script contract

const SYNTHETIC: Record<string, unknown> = { string: "example", integer: 1, float: 1.5, boolean: true, object: {}, "list[*]": [] };
const synthetic = (type: string) => structuredClone(SYNTHETIC[type] ?? null);

/** Whether a JSON value has a declared type, by the JSON Schema rules the runtime checks outputs with. */
export function hasType(value: unknown, type: string): boolean {
  switch (type) {
    case "string": return typeof value === "string";
    case "integer": return typeof value === "number" && Number.isInteger(value);
    case "float": return typeof value === "number";
    case "boolean": return typeof value === "boolean";
    case "object": return value !== null && typeof value === "object" && !Array.isArray(value);
    case "list[*]": return Array.isArray(value);
    default: return false;
  }
}

const stem = (p: string) => p.slice(p.lastIndexOf("/") + 1).replace(/\.[^.]*$/, "");

/** The runtime's `expects`: the next step's description, a router's expanded into its branches. */
function describeNext(d: Draft, id: string | undefined, depth = 0): unknown {
  const s = d.steps.find((x) => x.id === id);
  if (!s) return null;
  if (s.kind === "router") {
    return { step: s.name, kind: s.kind, branch_on: s.branchOn, branches: Object.fromEntries((s.branches ?? []).map((b) => [b.value, depth < 4 ? describeNext(d, b.target, depth + 1) : null])) };
  }
  return { step: s.name, kind: s.kind, inputs: Object.fromEntries(s.inputs.map((i) => [i.name, i.type])) };
}

/** Steps in the order a run first reaches them from the start step (breadth first; each once, so a loop ends). */
function runOrder(d: Draft): Step[] {
  const byId = new Map(d.steps.map((s) => [s.id, s]));
  const seen = new Set<string>(), order: Step[] = [];
  const start = startOf(d.steps);
  const queue = start ? [start] : [];
  while (queue.length) {
    const s = queue.shift()!;
    if (seen.has(s.id)) continue;
    seen.add(s.id);
    order.push(s);
    const next = s.kind === "router" ? [...(s.branches ?? []).map((b) => b.target), s.check?.to] : [s.next];
    for (const id of next) { const t = id ? byId.get(id) : undefined; if (t && !seen.has(t.id)) queue.push(t); }
  }
  return order;
}

/** Every execution script run in graph order: synthetic start inputs (the start step's), each step's outputs added
 *  to the state for the steps after it (a decision's answers and confidence keys and a client task's outputs are
 *  synthetic). Then every template's fields. */
export async function scriptContract(d: Draft, files: ZipFile[], runner: Runner): Promise<CheckResult> {
  const failures: string[] = [];
  const byPath = new Map(files.map((f) => [f.path, f]));
  const state: Record<string, unknown> = {};
  const order = runOrder(d);
  for (const i of startOf(d.steps)?.inputs ?? []) state[i.name] = synthetic(i.type);

  for (const s of order) {
    const label = `step \`${s.name}\``;
    if (s.kind === "decision") {
      for (const q of s.questions ?? []) if (!(q.name in state)) state[q.name] = synthetic(QUESTION_TYPES[q.type]);
      for (const q of s.confidence ?? []) if (q && !(confidenceKey(q) in state)) state[confidenceKey(q)] = synthetic(CONFIDENCE_TYPE);
    }
    if (s.kind === "client_task") for (const o of s.outputs ?? []) if (!(o.name in state)) state[o.name] = synthetic(o.type);
    if (s.kind !== "execution" || !s.script) continue;
    const inputs = Object.fromEntries(s.inputs.map((i) => [i.name, i.name in state ? state[i.name] : synthetic(i.type)]));
    const assets = Object.fromEntries((s.assets ?? []).map((a) => [stem(a), byPath.has(a) ? textOf(byPath.get(a)!) : ""]));
    const stdin = { state: inputs, assets, expects: describeNext(d, s.next) };
    const outputs = s.outputs ?? [];
    const run = await runner.probe(d.name, files, s.script, stdin, s.timeout);
    const fail = (why: string) => failures.push(`${label} (\`${s.script}\`): ${why}`);
    for (const o of outputs) if (!(o.name in state)) state[o.name] = synthetic(o.type);
    if (run.error) { fail(run.error); continue; }
    if (run.timedOut) { fail("timed out"); continue; }
    if (run.code !== 0) { fail(`exited with ${run.code}${run.stderr?.trim() ? `: ${run.stderr.trim().split("\n").slice(-3).join(" ")}` : ""}`); continue; }
    let out: unknown;
    try {
      out = (run.stdout ?? "").trim() === "" ? {} : JSON.parse(run.stdout!);
    } catch {
      fail(`stdout is not one JSON object: ${(run.stdout ?? "").trim().slice(0, 200)}`);
      continue;
    }
    if (!hasType(out, "object")) { fail(`stdout is ${JSON.stringify(out).slice(0, 80)}, not a JSON object`); continue; }
    const o = out as Record<string, unknown>;
    const declared = new Set(outputs.map((x) => x.name));
    for (const x of outputs) {
      if (!(x.name in o)) fail(`does not print the declared output \`${x.name}\``);
      else if (!hasType(o[x.name], x.type)) fail(`prints \`${x.name}\` as ${JSON.stringify(o[x.name]).slice(0, 60)}, which is not a ${x.type}`);
      else state[x.name] = o[x.name];
    }
    for (const key of Object.keys(o)) if (!declared.has(key)) fail(`prints \`${key}\`, which is not a declared output`);
  }

  for (const s of d.steps) {
    if (s.kind !== "client_task" || !s.template || !byPath.has(s.template)) continue;
    for (const why of templateFields(textOf(byPath.get(s.template)!), s)) failures.push(`step \`${s.name}\` (\`${s.template}\`): ${why}`);
  }
  return { name: "contract", ok: failures.length === 0, failures };
}

/** The `{field}`s of a template (Python `str.format` rules: `{{` and `}}` are literal braces) that the runtime
 *  cannot fill: anything but the step's inputs, `{assets[stem]}` for its assets, and `{meta.name}`. */
export function templateFields(text: string, s: Step): string[] {
  const inputs = new Set(s.inputs.map((i) => i.name));
  const assets = new Set((s.assets ?? []).map(stem));
  const out: string[] = [];
  const plain = text.replace(/\{\{|\}\}/g, "");
  for (const m of plain.matchAll(/\{([^{}]*)\}/g)) {
    const field = m[1].split(/[!:]/)[0];
    const root = /^[A-Za-z_][A-Za-z0-9_]*/.exec(field)?.[0];
    if (!root) { out.push(`\`{${m[1]}}\` is not a field the runtime can fill`); continue; }
    if (root === "assets") {
      const key = /^assets\[([^\]]*)\]$/.exec(field)?.[1];
      if (key === undefined || !assets.has(key)) out.push(`\`{${m[1]}}\` names no asset of the step`);
    } else if (root === "meta") {
      if (field !== "meta.name") out.push(`\`{${m[1]}}\`: only \`{meta.name}\` is filled`);
    } else if (!inputs.has(root) || field !== root) {
      out.push(`\`{${m[1]}}\` is not one of the step's inputs`);
    }
  }
  if (/\{|\}/.test(plain.replace(/\{[^{}]*\}/g, ""))) out.push("has a single `{` or `}` that is not a field; double it to write a brace");
  return out;
}

// ---------------------------------------------------------------------------------------------- completeness

/** True when the text holds nothing but comments and blank lines (for its file type), or nothing at all. */
export function onlyComments(path: string, text: string): boolean {
  let t = text;
  if (/\.(md|markdown|html?|xml|svg)$/i.test(path)) t = t.replace(/<!--[\s\S]*?-->/g, "");
  else if (/\.(py|sh|ya?ml|toml|cfg|ini)$/i.test(path)) t = t.split("\n").filter((l) => !l.trim().startsWith("#")).join("\n");
  return t.trim() === "";
}

export function completeness(result: Draft, files: ZipFile[]): CheckResult {
  const failures: string[] = [];
  const texts: Record<string, string> = {};
  for (const f of files) texts[f.path] = textOf(f);
  // The Studio's own notes name the marker; Accept drops them, so they are not the agent's to finish.
  const notes = (path: string) => (path === README_PATH || path === NOTES_PATH) && texts[path].includes(STUDIO_NOTE);
  for (const [path, text] of Object.entries(texts)) if (!notes(path) && text.includes(PLACEHOLDER_MARKER)) failures.push(`\`${path}\` still holds the placeholder marker \`${PLACEHOLDER_MARKER}\``);

  const named = new Set<string>();
  for (const s of result.steps) {
    for (const p of [s.script, s.template, ...(s.assets ?? []), ...(s.references ?? []).map((r) => r.path)]) if (p) named.add(p);
  }
  for (const p of [...named].sort()) {
    if (!(p in texts)) failures.push(`\`${p}\` is named by the graph but is not in the result`);
    else if (onlyComments(p, texts[p])) failures.push(`\`${p}\` is empty${texts[p].trim() ? " apart from comments" : ""}`);
  }
  for (const i of lint(result, { files: texts })) {
    if (i.tier === "unfinished" && i.code !== "placeholder_file") failures.push(`unfinished: ${i.message}`);
  }
  return { name: "completeness", ok: failures.length === 0, failures };
}

// ------------------------------------------------------------------------------------------------ accept

/** The Draft once a passing result is accepted: the prose the agent filled is written in, the result's files replace
 *  the placeholders, and everything the user made (ids, the imported SKILL.md text, the prompt) stays. */
export function acceptResult(draft: Draft, result: Draft, files: ZipFile[], keep: (f: ZipFile) => boolean): { draft: Draft; files: ZipFile[] } {
  const ids = new Map(result.steps.map((s, n) => [s.id, draft.steps[n]?.id ?? s.id]));
  const steps = result.steps.map((s) => ({
    ...s,
    id: ids.get(s.id)!,
    ...(s.next !== undefined && { next: ids.get(s.next) ?? s.next }),
    ...(s.branches && { branches: s.branches.map((b) => ({ ...b, target: b.target && (ids.get(b.target) ?? b.target) })) }),
  }));
  const next: Draft = { ...result, steps, origin: draft.origin, agentPrompt: draft.agentPrompt, metadata: draft.metadata ?? result.metadata };
  return { draft: next, files: files.filter((f) => f.path !== "SKILL.md" && keep(f)) };
}
