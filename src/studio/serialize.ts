// Draft <-> SKILL.md. The file is frontmatter, the runtime block verbatim, and one fenced YAML block. Export writes
// step names where the Draft holds ids; import does the reverse, and an edge to a name no step carries becomes an
// `unresolved:` id so the linter reports it instead of the import hiding it. Key order follows billing-support.

import { parse, stringify } from "yaml";
import { emptyDraft, FORMAT_VERSION, UNRESOLVED, type Branch, type Draft, type IOItem, type Question, type Requires, type Step, type StepKind } from "./draft";
import { patchYaml } from "./patch";
import { RUNTIME_BLOCK } from "./runtime-0.8";

const FRONTMATTER = /^---\s*\n(.*?)\n---\s*\n?(.*)$/s;
const FENCE = /```(?:yaml|yml)[ \t]*\n(.*?)\n```/gs;

type Obj = Record<string, unknown>;

// ------------------------------------------------------------------------------------------------- export

export function draftToSkillMd(draft: Draft): string {
  const front: Obj = { name: draft.name, description: draft.description };
  if (draft.compatibility !== undefined) front.compatibility = draft.compatibility;
  if (draft.license !== undefined) front.license = draft.license;
  if (draft.allowedTools !== undefined) front["allowed-tools"] = draft.allowedTools;
  front.metadata = { ...draft.metadata, "aip-version": FORMAT_VERSION };

  const nameOf = new Map(draft.steps.map((s) => [s.id, s.name]));
  const target = (id: string | undefined) => (id === undefined ? undefined : id.startsWith(UNRESOLVED) ? id.slice(UNRESOLVED.length) : nameOf.get(id) ?? id);

  const body: Obj = { purpose: draft.purpose, trigger_when: draft.triggerWhen };
  if (draft.doNotUseWhen.length) body.do_not_use_when = draft.doNotUseWhen;
  if (draft.requires) body.requires = requiresOut(draft.requires);
  // The start step is written first, wherever the draft holds it; the rest keep their order.
  const start = draft.steps.find((s) => s.kind === "start");
  const ordered = start ? [start, ...draft.steps.filter((s) => s !== start)] : draft.steps;
  body.steps = ordered.map((s) => stepOut(s, target));
  if (draft.antiPatterns.length) body.anti_patterns = draft.antiPatterns;

  // An imported draft keeps its own formatting wherever only values changed.
  const origin = draft.origin ? splitSkillMd(draft.origin) : null;
  const fm = (origin && patchYaml(origin.front, front)) ?? stringify(front, { lineWidth: 0 });
  const yaml = (origin?.body !== undefined && patchYaml(origin.body, body)) || stringify(body, { lineWidth: 0 });
  return `---\n${fm}---\n\n${RUNTIME_BLOCK.trim()}\n\n\`\`\`yaml\n${yaml}\`\`\`\n`;
}

function requiresOut(r: Requires): Obj {
  const out: Obj = { interpreter: r.interpreter.version === undefined ? { name: r.interpreter.name } : { name: r.interpreter.name, version: r.interpreter.version } };
  if (r.packages.length) out.packages = r.packages;
  if (r.tools.length) out.tools = r.tools;
  return out;
}

const ioOut = (items: IOItem[]) => items.map((i) => (i.description === undefined ? { name: i.name, type: i.type } : { name: i.name, type: i.type, description: i.description }));

function questionOut(q: Question): Obj {
  const out: Obj = { type: q.type, instructions: q.instructions };
  if (q.type === "noul") {
    if (q.criteria && (q.criteria.true !== undefined || q.criteria.false !== undefined)) {
      out.criteria = { ...(q.criteria.true !== undefined && { true: q.criteria.true }), ...(q.criteria.false !== undefined && { false: q.criteria.false }) };
    }
  } else if (q.type === "choice") {
    out.criteria = Object.fromEntries(q.criteria.map((c) => [c.label, c.description]));
  } else {
    out.criteria = q.criteria;
  }
  return out;
}

function stepOut(s: Step, target: (id: string | undefined) => string | undefined): Obj {
  const out: Obj = { name: s.name, kind: s.kind };
  if ((s.kind !== "end" && s.kind !== "start") || s.description) out.description = s.description;
  const put = (key: string, value: unknown) => { if (value !== undefined) out[key] = value; };
  const list = (key: string, value: unknown[] | undefined) => { if (value?.length) out[key] = value; };

  if (s.kind === "router") {
    put("branch_on", s.branchOn);
    if (s.check) {
      const check: Obj = { key: s.check.key };
      if (s.check.below !== undefined) check.below = s.check.below;
      const to = target(s.check.to);
      if (to !== undefined) check.to = to;
      out.confidence = check;
    }
    out.branches = Object.fromEntries((s.branches ?? []).map((b) => [b.value, target(b.target)]));
    return out;
  }
  out.inputs = ioOut(s.inputs);
  if (s.kind === "decision") {
    out.questions = Object.fromEntries((s.questions ?? []).map((q) => [q.name, questionOut(q)]));
    list("confidence", s.confidence);
    if (s.fallback) out.fallback = true;
    if (s.history) out.history = true;
  } else if (s.kind === "execution") {
    put("script", s.script);
    list("command", s.command);
    list("assets", s.assets);
    list("outputs", s.outputs && ioOut(s.outputs));
    put("timeout", s.timeout);
  } else if (s.kind === "client_task") {
    put("template", s.template);
    list("assets", s.assets);
    list("references", s.references?.map((r) => ({ path: r.path, description: r.description })));
    list("outputs", s.outputs && ioOut(s.outputs));
    if (s.framing === false) out.framing = false;
  }
  if (s.kind !== "end") put("inputs_to", target(s.next));
  return out;
}

// ------------------------------------------------------------------------------------------------- import

/** The Draft in a SKILL.md, however invalid the skill: only text that is not a SKILL.md at all throws. A key the
 *  Draft has no field for is dropped (the zip's other files are carried separately; see S4). */
export function skillMdToDraft(text: string): Draft {
  const parts = splitSkillMd(text);
  if (!parts) throw new Error("SKILL.md must begin with YAML frontmatter delimited by `---`");
  if (parts.body === undefined) throw new Error("SKILL.md has no fenced YAML block holding the procedure");
  const front = asObj(parse(parts.front));
  const body = asObj(parse(parts.body));

  const draft = emptyDraft();
  draft.name = str(front.name);
  draft.description = str(front.description);
  if (front.compatibility !== undefined) draft.compatibility = str(front.compatibility);
  if (front.license !== undefined) draft.license = str(front.license);
  if (front["allowed-tools"] !== undefined) draft.allowedTools = str(front["allowed-tools"]);
  const { "aip-version": version, ...metadata } = asObj(front.metadata);
  draft.aipVersion = str(version) || FORMAT_VERSION;
  if (Object.keys(metadata).length) draft.metadata = Object.fromEntries(Object.entries(metadata).map(([k, v]) => [k, str(v)]));

  draft.purpose = str(body.purpose);
  draft.triggerWhen = strs(body.trigger_when);
  draft.doNotUseWhen = strs(body.do_not_use_when);
  draft.antiPatterns = strs(body.anti_patterns);
  if (body.requires !== undefined && body.requires !== null) {
    const r = asObj(body.requires), i = asObj(r.interpreter);
    draft.requires = {
      interpreter: i.version === undefined ? { name: str(i.name) } : { name: str(i.name), version: str(i.version) },
      packages: strs(r.packages), tools: strs(r.tools),
    };
  }

  const raw = arr(body.steps).map(asObj);
  const ids = raw.map((_, n) => `s${n + 1}`);
  const idOf = new Map<string, string>();
  raw.forEach((s, n) => { if (!idOf.has(str(s.name))) idOf.set(str(s.name), ids[n]); });
  const edge = (name: unknown) => (name === undefined || name === null ? undefined : idOf.get(str(name)) ?? UNRESOLVED + str(name));
  draft.steps = raw.map((s, n) => stepIn(s, ids[n], edge));
  return draft;
}

/** The frontmatter's YAML and the procedure block's YAML, each ending in a line break; null when there is no
 *  frontmatter. A runtime block of any format version is skipped: none holds a fence. */
function splitSkillMd(text: string): { front: string; body?: string } | null {
  const match = FRONTMATTER.exec(text);
  if (!match) return null;
  const fence = [...match[2].matchAll(FENCE)][0];
  return { front: `${match[1]}\n`, body: fence ? `${fence[1]}\n` : undefined };
}

function stepIn(s: Obj, id: string, edge: (name: unknown) => string | undefined): Step {
  const kind = str(s.kind) as StepKind;
  const step: Step = { id, kind, name: str(s.name), description: str(s.description), inputs: ioIn(s.inputs) };
  if (kind === "router") {
    step.branchOn = str(s.branch_on);
    if (s.confidence !== undefined && s.confidence !== null) {
      const c = asObj(s.confidence);
      step.check = { key: str(c.key) };
      if (c.below !== undefined && c.below !== null) step.check.below = Number(c.below);
      if (c.to !== undefined && c.to !== null) step.check.to = edge(c.to);
    }
    step.branches = Object.entries(asObj(s.branches)).map(([value, to]): Branch => ({ value, target: edge(to) }));
    return step;
  }
  if (kind === "decision") {
    step.questions = Object.entries(asObj(s.questions)).map(([name, q]) => questionIn(name, asObj(q)));
    if (s.confidence !== undefined) step.confidence = strs(s.confidence);
    if (s.fallback === true) step.fallback = true;
    if (s.history === true) step.history = true;
  } else if (kind === "execution") {
    if (s.script !== undefined) step.script = str(s.script);
    if (s.command !== undefined) step.command = strs(s.command);
    if (s.timeout !== undefined) step.timeout = Number(s.timeout);
    step.assets = strs(s.assets);
    step.outputs = ioIn(s.outputs);
  } else if (kind === "client_task") {
    if (s.template !== undefined) step.template = str(s.template);
    step.assets = strs(s.assets);
    step.references = arr(s.references).map(asObj).map((r) => ({ path: str(r.path), description: str(r.description) }));
    step.outputs = ioIn(s.outputs);
    if (s.framing === false) step.framing = false;
  }
  if (kind !== "end") step.next = edge(s.inputs_to);
  return step;
}

function questionIn(name: string, q: Obj): Question {
  const instructions = str(q.instructions);
  const type = str(q.type);
  if (type === "choice") {
    return { name, type, instructions, criteria: Object.entries(asObj(q.criteria)).map(([label, d]) => ({ label, description: d === null || d === undefined ? null : str(d) })) };
  }
  if (type === "score") return { name, type, instructions, criteria: strs(q.criteria) };
  const c = asObj(q.criteria);
  const criteria = { ...(c.true !== undefined && { true: str(c.true) }), ...(c.false !== undefined && { false: str(c.false) }) };
  return { name, type: "noul", instructions, ...(Object.keys(criteria).length && { criteria }) };
}

const ioIn = (v: unknown): IOItem[] => arr(v).map(asObj).map((i) => (i.description === undefined ? { name: str(i.name), type: str(i.type) } : { name: str(i.name), type: str(i.type), description: str(i.description) }));

function asObj(v: unknown): Obj { return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {}; }
function arr(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function str(v: unknown): string { return v === undefined || v === null ? "" : String(v); }
function strs(v: unknown): string[] { return arr(v).map(str); }
