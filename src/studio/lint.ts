// The Studio's linter: a TypeScript port of aip-spec's frontmatter, schema, graph and state rules (`skill.py`,
// `models.py`), run on a Draft in the browser on every edit. Codes are aip-spec's where one exists; the models'
// pattern and length rules are all `schema_violation`, as there. The real `aip-spec validate` stays the authority:
// e2e/lint-parity.spec.ts runs both over the same fixtures and fails on any disagreement in the codes.
//
// Four tiers. `error`: aip-spec would reject it. `warning`: aip-spec's own warnings (a route an LLM steers with
// nothing recorded) and Studio-only advice (S5). `info`: aip-spec's information (a key with several producers).
// `unfinished`: valid or fixable, but a placeholder or an empty field a template may carry.

import { BRANCHABLE_TYPES, CONFIDENCE_TYPE, QUESTION_TYPES, RUNNABLE_KINDS, UNRESOLVED, confidenceKey, type Draft, type Step } from "./draft";

export type Tier = "error" | "unfinished" | "warning" | "info";

export interface Issue {
  tier: Tier;
  code: string;
  message: string;
  stepId?: string;
  /** The Draft field the issue is about, as a path inside the step (`inputs[1].type`) or the Draft (`purpose`). */
  field?: string;
  /** The state key the issue is about, where one is: what a quick fix declares. */
  key?: string;
}

export interface LintOptions {
  /** The text of the skill's files by path, to find placeholders still holding the marker. */
  files?: Record<string, string>;
}

export const PLACEHOLDER_MARKER = "AIP-STUDIO-PLACEHOLDER";

const STEP_NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const QUESTION_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const SKILL_NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const PACKAGE = /^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?(>=[0-9]+(\.[0-9]+)*)?$/;
const VERSION = /^[0-9]+(\.[0-9]+)*$/;
const PROGRAM = /^[A-Za-z0-9][A-Za-z0-9._+-]*$/;
const DEFAULT_LAUNCHER = "python";
const DATA_TYPE_SET = new Set(["string", "integer", "float", "boolean", "object", "list[*]"]);
const KIND_SET = new Set<string>(["start", ...RUNNABLE_KINDS, "router", "end"]);

/** A step with its edges resolved to names, the form aip-spec's checks work on. */
interface R {
  s: Step;
  index: number;
  name: string;
  /** Every step this one hands off to, with the Draft field that names it. */
  edges: { target: string; field: string }[];
  targets: string[];
  /** The name `inputs_to` points at, for the router-fed-by-decision check. */
  inputsTo?: string;
}

export function lint(draft: Draft, options: LintOptions = {}): Issue[] {
  const issues: Issue[] = [];
  const add = (tier: Tier, code: string, message: string, step?: Step, field?: string, key?: string) => {
    issues.push({ tier, code, message, ...(step && { stepId: step.id }), ...(field && { field }), ...(key !== undefined && { key }) });
  };
  const err = (code: string, message: string, step?: Step, field?: string, key?: string) => add("error", code, message, step, field, key);

  frontmatter(draft, err);
  schema(draft, err);
  if (draft.steps.length > 0) graph(draft, add);
  unfinished(draft, options, add);
  if (draft.steps.length > 0) studio(draft, add);
  return issues;
}

/** Error codes only the Studio reports. Each one comes with an aip-spec error on the same draft (docs/studio-lint.md),
 *  so the parity test leaves them out of the comparison. */
export const STUDIO_ONLY_ERRORS = new Set(["loop_without_router"]);

/** Warning codes only the Studio reports (S5); aip-spec's own warnings are every other warning the linter gives. */
export const STUDIO_ONLY_WARNINGS = new Set(["redundant_branches", "numeric_choice_labels", "duplicate_score_levels", "execution_without_outputs", "dead_key", "name_collision"]);

// ------------------------------------------------------------------------------------------ frontmatter

type Err = (code: string, message: string, step?: Step, field?: string, key?: string) => void;
type Add = (tier: Tier, code: string, message: string, step?: Step, field?: string, key?: string) => void;

function frontmatter(d: Draft, err: Err): void {
  if (!d.name) err("missing_required_frontmatter", "`name` is required", undefined, "name");
  else if (d.name.length > 64) err("invalid_name", `\`name\` must be 1–64 characters; got ${d.name.length}`, undefined, "name");
  else if (!SKILL_NAME.test(d.name)) err("invalid_name", "`name` must contain only lowercase a–z, 0–9, and hyphens, with no leading/trailing and no consecutive hyphens", undefined, "name");

  if (!d.description.trim()) err("invalid_description", "`description` must be a non-empty string", undefined, "description");
  else if (d.description.length > 1024) err("invalid_description", `\`description\` must be 1–1024 characters; got ${d.description.length}`, undefined, "description");

  if (d.compatibility !== undefined && !(d.compatibility.length >= 1 && d.compatibility.length <= 500)) {
    err("invalid_compatibility", `\`compatibility\` must be 1–500 characters; got ${d.compatibility.length}`, undefined, "compatibility");
  }
}

// ----------------------------------------------------------------------------------------------- schema

/** The models' own rules (patterns, lengths, required fields). aip-spec reports every one as `schema_violation`. */
function schema(d: Draft, err: Err): void {
  const bad = (message: string, step?: Step, field?: string) => err("schema_violation", message, step, field);
  const label = (s: Step) => (s.name ? `step \`${s.name}\`` : `an unnamed ${s.kind} step`);

  if (d.steps.length < 3) bad(`\`steps\` needs at least 3 steps (a start, a runnable step and an end); there ${d.steps.length === 1 ? "is 1" : `are ${d.steps.length}`}`, undefined, "steps");
  if (d.triggerWhen.length < 1) bad("`trigger_when` needs at least 1 entry", undefined, "triggerWhen");

  if (d.requires) {
    const r = d.requires;
    if (!PROGRAM.test(r.interpreter.name)) bad(`\`requires.interpreter.name\` must be a program name such as \`python\`; got \`${r.interpreter.name}\``, undefined, "requires.interpreter.name");
    if (r.interpreter.version !== undefined && !VERSION.test(r.interpreter.version)) bad(`\`requires.interpreter.version\` must be dotted numbers such as \`3.10\`; got \`${r.interpreter.version}\``, undefined, "requires.interpreter.version");
    r.packages.forEach((p, i) => { if (!PACKAGE.test(p)) bad(`\`requires.packages[${i}]\` \`${p}\` is not a pip distribution name with an optional \`>=\` version`, undefined, `requires.packages[${i}]`); });
    r.tools.forEach((t, i) => { if (!PROGRAM.test(t)) bad(`\`requires.tools[${i}]\` \`${t}\` is not an executable name`, undefined, `requires.tools[${i}]`); });
  }

  for (const s of d.steps) {
    if (!STEP_NAME.test(s.name)) bad(`${label(s)}: the name must be kebab-case (lowercase a–z, 0–9, single hyphens)`, s, "name");
    if (!KIND_SET.has(s.kind)) {
      bad(`${label(s)} has an unknown kind \`${s.kind}\``, s, "kind");
      continue;
    }

    const io = (items: Step["inputs"] | undefined, which: "inputs" | "outputs") => {
      (items ?? []).forEach((item, i) => {
        if (!item.name) bad(`${label(s)}: ${which}[${i}] has no name`, s, `${which}[${i}].name`);
        if (!DATA_TYPE_SET.has(item.type)) bad(`${label(s)}: ${which}[${i}] has type \`${item.type}\`, which is not one of string, integer, float, boolean, object, list[*]`, s, `${which}[${i}].type`);
      });
    };
    if (s.kind !== "router") io(s.inputs, "inputs");
    if (s.kind === "execution" || s.kind === "client_task") io(s.outputs, "outputs");

    if (s.kind === "start" && s.next === undefined) bad(`${label(s)} has no next step (\`inputs_to\`); the start step names the first runnable step`, s, "next");
    if (RUNNABLE_KINDS.includes(s.kind) && s.next === undefined) bad(`${label(s)} has no next step (\`inputs_to\`); every runnable step names the step that receives its output`, s, "next");

    if (s.kind === "decision") {
      const questions = s.questions ?? [];
      if (questions.length < 1) bad(`${label(s)} needs at least 1 question`, s, "questions");
      const seen = new Set<string>();
      questions.forEach((q, i) => {
        if (!QUESTION_NAME.test(q.name)) bad(`${label(s)}: question name \`${q.name}\` must be an identifier (letters, digits, underscore; not starting with a digit)`, s, `questions[${i}].name`);
        if (seen.has(q.name)) err("duplicate_question_name", `${label(s)} has two questions named \`${q.name}\``, s, `questions[${i}].name`);
        seen.add(q.name);
        if (q.type === "choice") {
          const labels = new Set<string>();
          q.criteria.forEach((c, j) => {
            if (labels.has(c.label)) err("duplicate_choice_label", `${label(s)}: question \`${q.name}\` lists the label \`${c.label}\` twice`, s, `questions[${i}].criteria[${j}]`);
            labels.add(c.label);
          });
          if (labels.size < 2) bad(`${label(s)}: choice question \`${q.name}\` needs at least 2 labels`, s, `questions[${i}].criteria`);
        } else if (q.type === "score") {
          if (q.criteria.length < 2 || q.criteria.length > 10) bad(`${label(s)}: score question \`${q.name}\` needs 2 to 10 levels; has ${q.criteria.length}`, s, `questions[${i}].criteria`);
        } else if (q.type !== "noul") {
          bad(`${label(s)}: question \`${(q as { name: string }).name}\` has an unknown type`, s, `questions[${i}].type`);
        }
      });
      (s.confidence ?? []).forEach((name, k) => {
        if (!QUESTION_NAME.test(name)) bad(`${label(s)}: \`confidence\` entry \`${name}\` must be a question name (letters, digits, underscore; not starting with a digit)`, s, `confidence[${k}]`);
      });
    }

    if (s.kind === "execution") {
      if (!/^scripts\/.+/.test(s.script ?? "")) bad(`${label(s)}: \`script\` must be a path under \`scripts/\`; got \`${s.script ?? ""}\``, s, "script");
      if (s.command !== undefined && (s.command.length < 1 || s.command.some((c) => !c))) bad(`${label(s)}: \`command\` must be a non-empty list of non-empty arguments`, s, "command");
      if (s.timeout !== undefined && !(s.timeout > 0)) bad(`${label(s)}: \`timeout\` must be greater than 0`, s, "timeout");
    }
    if (s.kind === "execution" || s.kind === "client_task") {
      (s.assets ?? []).forEach((a, i) => { if (!/^assets\/.+/.test(a)) bad(`${label(s)}: asset \`${a}\` must be a path under \`assets/\``, s, `assets[${i}]`); });
    }
    if (s.kind === "client_task") {
      if (!/^assets\/.+/.test(s.template ?? "")) bad(`${label(s)}: \`template\` must be a path under \`assets/\`; got \`${s.template ?? ""}\``, s, "template");
      (s.references ?? []).forEach((r, i) => { if (!/^references\/.+/.test(r.path)) bad(`${label(s)}: reference \`${r.path}\` must be a path under \`references/\``, s, `references[${i}].path`); });
    }

    if (s.kind === "router") {
      if (!s.branchOn) bad(`${label(s)}: \`branch_on\` is required`, s, "branchOn");
      if (s.check) {
        if (!s.check.key) bad(`${label(s)}: the confidence check names no key`, s, "check.key");
        if (s.check.below === undefined) bad(`${label(s)}: the confidence check has no bound (\`below\`)`, s, "check.below");
        else if (!(s.check.below >= 0 && s.check.below <= 1)) bad(`${label(s)}: the confidence check's bound must be between 0 and 1; got ${s.check.below}`, s, "check.below");
        if (s.check.to === undefined) bad(`${label(s)}: the confidence check names no step to go to (\`to\`)`, s, "check.to");
      }
      const branches = s.branches ?? [];
      const values = new Set<string>();
      branches.forEach((b, i) => {
        if (values.has(b.value)) err("duplicate_branch_value", `${label(s)} has two branches for the value \`${b.value}\``, s, `branches[${i}].value`);
        values.add(b.value);
        if (b.target === undefined) bad(`${label(s)}: the branch for \`${b.value}\` names no step`, s, `branches[${i}].target`);
      });
      if (values.size < 2) bad(`${label(s)}: a router needs at least 2 branches; has ${values.size}`, s, "branches");
    }
  }
}

// ----------------------------------------------------------------------------------------------- graph

const unique = <T,>(items: T[]) => [...new Set(items)];

function resolve(draft: Draft): R[] {
  const byId = new Map(draft.steps.map((s) => [s.id, s]));
  const nameOf = (id: string | undefined): string | undefined => {
    if (id === undefined) return undefined;
    if (id.startsWith(UNRESOLVED)) return id.slice(UNRESOLVED.length);
    return byId.get(id)?.name ?? id;
  };
  return draft.steps.map((s, index) => {
    const edges: { target: string | undefined; field: string }[] = [];
    if (s.kind === "router") {
      (s.branches ?? []).forEach((b, i) => edges.push({ target: nameOf(b.target), field: `branches[${i}].target` }));
      if (s.check) edges.push({ target: nameOf(s.check.to), field: "check.to" });
    } else if (s.kind !== "end") {
      edges.push({ target: nameOf(s.next), field: "next" });
    }
    const known = edges.filter((e): e is { target: string; field: string } => e.target !== undefined);
    return { s, index, name: s.name, edges: known, targets: known.map((e) => e.target), inputsTo: s.kind === "router" || s.kind === "end" ? undefined : nameOf(s.next) };
  });
}

/** Keys a step reads from the state. The start step reads none: its inputs are what the client supplies. A router's
 *  confidence key is checked apart (it need only be declared on some path, not every path). */
const consumed = (r: R): string[] =>
  r.s.kind === "router" ? (r.s.branchOn ? [r.s.branchOn] : []) : r.s.kind === "start" ? [] : r.s.inputs.map((i) => i.name).filter(Boolean);

/** Keys a step adds to the state: the start its inputs, a decision its question names and the confidence keys it
 *  names, an execution or client task its outputs. */
const produced = (r: R): string[] => {
  if (r.s.kind === "start") return r.s.inputs.map((i) => i.name).filter(Boolean);
  if (r.s.kind === "decision") {
    return [...(r.s.questions ?? []).map((q) => q.name).filter(Boolean), ...(r.s.confidence ?? []).filter(Boolean).map(confidenceKey)];
  }
  return (r.s.outputs ?? []).map((i) => i.name).filter(Boolean);
};

function graph(draft: Draft, add: Add): void {
  const err: Err = (code, message, step, field, key) => add("error", code, message, step, field, key);
  const steps = resolve(draft);
  const byName = new Map<string, R>();
  for (const r of steps) {
    if (byName.has(r.name)) {
      if (r.name) err("duplicate_step_name", `step name \`${r.name}\` is declared more than once`, r.s, "name");
    } else byName.set(r.name, r);
  }

  const starts = steps.filter((r) => r.s.kind === "start");
  if (starts.length === 0) err("missing_start_step", "procedure has no step of kind `start`; add one holding the procedure's inputs, with `inputs_to` naming the first runnable step", undefined, "steps");
  else if (starts.length > 1) err("multiple_start_steps", `procedure must have exactly one \`start\` step; found [${starts.map((r) => `'${r.name}'`).join(", ")}]`, undefined, "steps");
  const start: R | undefined = starts[0];

  const ends = steps.filter((r) => r.s.kind === "end");
  if (ends.length === 0) err("missing_end_step", "procedure has no step of kind `end`", undefined, "steps");
  else if (ends.length > 1) err("multiple_end_steps", `procedure must have exactly one \`end\` step; found [${ends.map((r) => `'${r.name}'`).join(", ")}]`, undefined, "steps");

  for (const r of steps) {
    for (const { target, field } of r.edges) {
      if (!byName.has(target)) {
        err("unknown_step_reference", `step \`${r.name}\` hands off to \`${target}\`, which is not a declared step`, r.s, field);
      } else if (start && target === start.name) {
        err("edge_into_start", `step \`${r.name}\` hands off to \`${target}\`, the start step; a run begins there and nothing returns to it`, r.s, field);
      }
    }
  }

  for (const r of steps) {
    if (r.s.kind !== "decision") continue;
    const names = new Set((r.s.questions ?? []).map((q) => q.name));
    (r.s.confidence ?? []).forEach((q, k) => {
      if (!names.has(q)) err("unknown_confidence_question", `decision \`${r.name}\` names \`${q}\` in \`confidence\`, which is not one of its questions [${[...names].sort().map((n) => `'${n}'`).join(", ")}]`, r.s, `confidence[${k}]`);
    });
  }

  const reachable = (from: string): Set<string> => {
    const seen = new Set<string>();
    const stack = [from];
    while (stack.length) {
      const current = stack.pop()!;
      const r = byName.get(current);
      if (seen.has(current) || !r) continue;
      seen.add(current);
      stack.push(...r.targets);
    }
    return seen;
  };

  if (start) {
    const fromStart = reachable(start.name);
    for (const r of steps) {
      if (!fromStart.has(r.name)) err("unreachable_step", `step \`${r.name}\` cannot be reached from the start step \`${start.name}\``, r.s);
    }
  }
  if (ends.length === 1) {
    for (const r of steps) {
      if (r.s.kind !== "end" && !reachable(r.name).has(ends[0].name)) err("no_path_to_end", `step \`${r.name}\` has no path to the end step \`${ends[0].name}\``, r.s);
    }
  }

  // Routers fed directly by a decision: branch values must be answers that question can give.
  for (const r of steps) {
    if (r.s.kind !== "router") continue;
    for (const feeder of steps.filter((f) => f.inputsTo === r.name && f.s.kind === "decision")) {
      const q = (feeder.s.questions ?? []).find((x) => x.name === r.s.branchOn);
      if (!q) continue;
      const allowed = q.type === "noul" ? ["true", "false"] : q.type === "choice" ? q.criteria.map((c) => c.label) : q.criteria.map((_, n) => String(n));
      (r.s.branches ?? []).forEach((b, i) => {
        if (!allowed.includes(b.value)) {
          err("unknown_branch_value", `router \`${r.name}\` branches on \`${r.s.branchOn}\`, a ${q.type} question in \`${feeder.name}\`, but \`${b.value}\` is not one of its possible answers [${[...allowed].sort().map((a) => `'${a}'`).join(", ")}]`, r.s, `branches[${i}].value`);
        }
      });
    }
  }

  state(steps, byName, start, add);
  sources(steps, byName, add);
  requires(draft, steps, err);

  for (const r of steps) {
    if (r.s.kind === "router") continue;
    const seen = new Set<string>();
    r.s.inputs.forEach((item, j) => {
      if (seen.has(item.name)) err("duplicate_input_name", `step \`${r.name}\` declares input \`${item.name}\` more than once`, r.s, `inputs[${j}].name`);
      seen.add(item.name);
    });
  }
}

/** The state contract. A literal port of aip-spec's `check_state`: every consumed key has a producer on every path to
 *  its consumer (the start step produces its inputs), client tasks declare outputs, every declaration of a key agrees
 *  on its type, a router branches on a value it can match and checks a `float`. A key with several producers is
 *  information, not a fault: a later producer overwrites the value where a run passes through both. */
function state(steps: R[], byName: Map<string, R>, start: R | undefined, add: Add): void {
  const err: Err = (code, message, step, field, key) => add("error", code, message, step, field, key);

  // Rule 3: a client task's outputs are what the client is asked to answer with.
  for (const r of steps) {
    if (r.s.kind === "client_task" && (r.s.outputs ?? []).length === 0) {
      err("missing_outputs", `client_task \`${r.name}\` declares no \`outputs\`; they are what the client is asked to answer with, so declare each key the answer adds to the state`, r.s, "outputs");
    }
    const seen = new Set<string>();
    (r.s.outputs ?? []).forEach((item, j) => {
      if (seen.has(item.name)) err("duplicate_output_name", `step \`${r.name}\` declares output \`${item.name}\` more than once`, r.s, `outputs[${j}].name`);
      seen.add(item.name);
    });
  }

  // Several producers of one key: allowed, and said, so authors see the overwrite.
  const producers = new Map<string, R[]>();
  for (const r of steps) for (const key of unique(produced(r))) producers.set(key, [...(producers.get(key) ?? []), r]);
  for (const [key, makers] of producers) {
    if (makers.length > 1) {
      const names = makers.map((m) => `\`${m.name}\`${m.s.kind === "start" ? " (a start input)" : ""}`).join(", ");
      add("info", "duplicate_producer", `key \`${key}\` has more than one producer: ${names}; where a run passes through both, the later one overwrites the value`, makers[1].s, undefined, key);
    }
  }

  // Rule 4: every declaration of a key agrees on its type. The first in step order is the reference.
  const reference = new Map<string, [string, string]>();
  for (const r of steps) {
    for (const d of declarations(r)) {
      const expected = reference.get(d.key);
      if (!expected) { reference.set(d.key, [d.type, d.citedAs]); continue; }
      if (expected[0] !== d.type) {
        err("type_mismatch", `${d.says}, but it is \`${expected[0]}\` (${expected[1]}); a key has one type everywhere it is declared`, r.s, d.field);
      }
    }
  }
  for (const r of steps) {
    if (r.s.kind !== "router" || !r.s.branchOn) continue;
    const expected = reference.get(r.s.branchOn);
    if (expected && !BRANCHABLE_TYPES.includes(expected[0])) {
      err("unbranchable_type", `router \`${r.name}\` branches on \`${r.s.branchOn}\`, which is \`${expected[0]}\` (${expected[1]}); a router branches on a \`boolean\`, \`string\` or \`integer\``, r.s, "branchOn");
    }
  }

  // Rule 1: keys available on every path (must-availability over the graph, cycles included); a router's confidence
  // key need only be declared on some path (may-availability).
  const must = availability(steps, byName, start, intersect);
  const may = availability(steps, byName, start, union);
  const onStart = start ? ` on the start step \`${start.name}\`` : " on the start step";
  for (const r of steps) {
    const have = must.get(r.name);
    if (have == null) continue;                    // unreachable; reported elsewhere
    for (const k of unique(consumed(r)).filter((k) => !have.has(k))) {
      if (r.s.kind === "router") {
        err("unproduced_input", `router \`${r.name}\` branches on \`${k}\`, which no step produces on every path to it; pick a key that reaches the router, or declare \`${k}\`${onStart} if the client supplies it, or as an \`output\` of an upstream step`, r.s, "branchOn", k);
        continue;
      }
      err("unproduced_input", `step \`${r.name}\` consumes \`${k}\`, which no step produces on every path to it; declare it${onStart} if the client supplies it, or as an \`output\` of an upstream step`, r.s, "inputs", k);
    }
    if (r.s.kind === "router" && r.s.check?.key && !(may.get(r.name) ?? new Set()).has(r.s.check.key)) {
      err("unproduced_input", `router \`${r.name}\` checks \`${r.s.check.key}\`, which no step produces on any path to it; name the question in a decision's \`confidence\` list (which emits \`<question>_confidence\`), or declare the key as an output of an upstream step`, r.s, "check.key", r.s.check.key);
    }
  }
}

interface Declaration { key: string; type: string; says: string; citedAs: string; field: string }

/** Every (key, type) a step declares, in order: a start's inputs, a runnable step's inputs then questions and
 *  confidence keys or outputs, an end's inputs, a router's confidence key. */
function declarations(r: R): Declaration[] {
  const s = r.s;
  const out: Declaration[] = [];
  if (s.kind === "router") {
    if (s.check?.key) {
      out.push({ key: s.check.key, type: CONFIDENCE_TYPE, says: `router \`${r.name}\` checks \`${s.check.key}\` as a \`${CONFIDENCE_TYPE}\``, citedAs: `the confidence check of \`${r.name}\``, field: "check.key" });
    }
    return out;
  }
  s.inputs.forEach((item, j) => {
    if (!item.name) return;
    const noun = s.kind === "start" ? "start input" : "input";
    out.push({ key: item.name, type: item.type, says: `step \`${r.name}\` declares ${noun} \`${item.name}\` as \`${item.type}\``, citedAs: s.kind === "start" ? `start input on \`${r.name}\`` : `input of \`${r.name}\``, field: `inputs[${j}].type` });
  });
  if (s.kind === "decision") {
    (s.questions ?? []).forEach((q, i) => {
      if (!q.name) return;
      const type = QUESTION_TYPES[q.type] ?? q.type;
      out.push({ key: q.name, type, says: `step \`${r.name}\` answers \`${q.name}\` with a ${q.type} question, a \`${type}\``, citedAs: `a ${q.type} question in \`${r.name}\``, field: `questions[${i}]` });
    });
    (s.confidence ?? []).forEach((q, k) => {
      if (!q) return;
      out.push({ key: confidenceKey(q), type: CONFIDENCE_TYPE, says: `step \`${r.name}\` emits \`${confidenceKey(q)}\`, the confidence of \`${q}\`, a \`${CONFIDENCE_TYPE}\``, citedAs: `the confidence of \`${q}\` in \`${r.name}\``, field: `confidence[${k}]` });
    });
  }
  (s.outputs ?? []).forEach((item, j) => {
    if (!item.name) return;
    out.push({ key: item.name, type: item.type, says: `step \`${r.name}\` declares output \`${item.name}\` as \`${item.type}\``, citedAs: `output of \`${r.name}\``, field: `outputs[${j}].type` });
  });
  return out;
}

/** Each key's type and where it comes from, first declaration in step order winning (aip-spec's reference). */
function typeTable(steps: R[]): Map<string, [string, string]> {
  const table = new Map<string, [string, string]>();
  for (const r of steps) for (const d of declarations(r)) if (!table.has(d.key)) table.set(d.key, [d.type, d.citedAs]);
  return table;
}

const intersect = (sets: Set<string>[]) => sets.reduce((a, b) => new Set([...a].filter((k) => b.has(k))));
const union = (sets: Set<string>[]) => new Set(sets.flatMap((s) => [...s]));

/** The keys known to be in the state when each step starts: a fixed point over the graph, so a loop is handled.
 *  `combine` is intersection for must-availability (on every path) or union for may-availability (on some path).
 *  Null marks a step nothing reaches; with no start step, every step. */
function availability(steps: R[], byName: Map<string, R>, start: R | undefined, combine: (sets: Set<string>[]) => Set<string>): Map<string, Set<string> | null> {
  const available = new Map<string, Set<string> | null>(steps.map((r) => [r.name, null]));
  if (start) available.set(start.name, new Set());
  const preds = new Map<string, R[]>();
  for (const r of steps) for (const target of r.targets) preds.set(target, [...(preds.get(target) ?? []), r]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const r of steps) {
      if (r === start || byName.get(r.name) !== r) continue;
      const known = (preds.get(r.name) ?? [])
        .filter((p) => available.get(p.name) != null)
        .map((p) => new Set([...available.get(p.name)!, ...produced(p)]));
      if (known.length === 0) continue;
      const next = combine(known);
      const old = available.get(r.name);
      if (!old || old.size !== next.size || [...next].some((k) => !old.has(k))) {
        available.set(r.name, next);
        changed = true;
      }
    }
  }
  return available;
}

export interface AvailableKey { name: string; type: string }

/** For each step id, the keys it may declare as inputs: everything produced on every path to it (the start step
 *  produces its inputs), with their types. The same computation `unproduced_input` is judged by, so a pick from this
 *  list never raises it. A step nothing reaches has none. */
export function availableKeys(draft: Draft): Map<string, AvailableKey[]> {
  const out = new Map<string, AvailableKey[]>();
  if (draft.steps.length === 0) return out;
  const steps = resolve(draft);
  const byName = new Map<string, R>();
  for (const r of steps) if (!byName.has(r.name)) byName.set(r.name, r);
  const start = steps.find((r) => r.s.kind === "start");
  const available = availability(steps, byName, start, intersect);
  const types = typeTable(steps);
  for (const r of steps) {
    const have = byName.get(r.name) === r ? available.get(r.name) : null;
    out.set(r.s.id, have ? [...have].map((name) => ({ name, type: types.get(name)?.[0] ?? "string" })) : []);
  }
  return out;
}

// ---------------------------------------------------------------------------------- the sources of a route

export type SourceClass = "deterministic" | "measured" | "unmeasured";
const CLASS_RANK: Record<SourceClass, number> = { deterministic: 0, measured: 1, unmeasured: 2 };

interface Source { producer: R; cls: SourceClass; why: string }

/** What kind of source one producer of a router's branch key is, and why in a phrase (aip-spec's `_classify`).
 *  Deterministic: a start input, or a script's output the router does not read a confidence from. Measured: a
 *  decision model (no fallback) whose confidence for the branch question the router checks, or a script or client
 *  task whose own declared number the router checks. Unmeasured: a decision the client may answer by hand, or a
 *  client task's output the router does not check. */
function classify(router: R, producer: R): [SourceClass, string] {
  const checked = router.s.check?.key;
  const key = router.s.branchOn ?? "";
  const p = producer.s;
  if (p.kind === "start") return ["deterministic", `\`${key}\` is a start input`];
  if (p.kind === "execution" || p.kind === "client_task") {
    const own = (p.outputs ?? []).map((o) => o.name);
    const label = p.kind === "execution" ? "script" : "client task";
    if (checked && own.includes(checked)) return ["measured", `${label} \`${producer.name}\` declares \`${checked}\`, the number the router checks, beside \`${key}\``];
    if (p.kind === "execution") return ["deterministic", `\`${key}\` is an output of script \`${producer.name}\``];
    return ["unmeasured", `\`${key}\` is an output of client task \`${producer.name}\`, chosen by the client's own judgment, and the router checks no number the task declares`];
  }
  // a decision
  if (p.fallback) return ["unmeasured", `decision \`${producer.name}\` answers \`${key}\` with \`fallback: true\`, so the client may have chosen it by hand`];
  if (!(p.confidence ?? []).includes(key)) return ["unmeasured", `decision \`${producer.name}\` does not name \`${key}\` in its \`confidence\` list, so the model's confidence is not recorded`];
  if (checked !== confidenceKey(key)) return ["unmeasured", `decision \`${producer.name}\` emits \`${confidenceKey(key)}\` but the router does not check it`];
  return ["measured", `decision \`${producer.name}\` answers \`${key}\` with a decision model and the router checks \`${checked}\``];
}

/** For each router (the first of its name): every producer of its branch key from which the router can be reached,
 *  with the producer's class and the reason. */
function routeSources(steps: R[], byName: Map<string, R>): Map<R, Source[]> {
  const reaches = (from: string, target: string): boolean => {
    const seen = new Set<string>();
    const stack = [from];
    while (stack.length) {
      const current = stack.pop()!;
      const r = byName.get(current);
      if (seen.has(current) || !r) continue;
      seen.add(current);
      for (const next of r.targets) {
        if (next === target) return true;
        stack.push(next);
      }
    }
    return false;
  };
  const out = new Map<R, Source[]>();
  for (const router of steps) {
    if (router.s.kind !== "router" || byName.get(router.name) !== router) continue;
    const key = router.s.branchOn;
    const found: Source[] = [];
    if (key) {
      for (const producer of steps) {
        if (produced(producer).includes(key) && reaches(producer.name, router.name)) {
          const [cls, why] = classify(router, producer);
          found.push({ producer, cls, why });
        }
      }
    }
    out.set(router, found);
  }
  return out;
}

const worstOf = (found: Source[]): SourceClass => found.reduce<SourceClass>((w, f) => (CLASS_RANK[f.cls] > CLASS_RANK[w] ? f.cls : w), "deterministic");

/** The class of every router's source, by step id: `deterministic`, `measured` or `unmeasured`, the worst of its
 *  branch key's producers (aip-spec's `classify_sources`, what the server stores and the Procedure page shows). */
export function classifySources(draft: Draft): Map<string, SourceClass> {
  const steps = resolve(draft);
  const byName = new Map<string, R>();
  for (const r of steps) if (!byName.has(r.name)) byName.set(r.name, r);
  const out = new Map<string, SourceClass>();
  for (const [router, found] of routeSources(steps, byName)) out.set(router.s.id, worstOf(found));
  return out;
}

/** What the class of a route says to its author (aip-spec's `check_sources`): a router whose check reads a number
 *  nothing calibrated (`confidence_on_unmeasured_source`), a router an LLM steers with nothing recorded
 *  (`unmeasured_route`), both warnings; a router checking a confidence a script or client task declared itself
 *  (`declared_confidence`), information. A deterministic route says nothing. */
function sources(steps: R[], byName: Map<string, R>, add: Add): void {
  const fix = "decide the key with a decision model (`fallback: false`) that names the question in its `confidence` list, and check `<question>_confidence` on the router";
  for (const [router, found] of routeSources(steps, byName)) {
    const s = router.s;
    const worst = worstOf(found);
    const reasons = found.filter((f) => f.cls === "unmeasured").map((f) => f.why).join("; ");
    if (worst === "unmeasured" && s.check) {
      add("warning", "confidence_on_unmeasured_source", `router \`${router.name}\` checks \`${s.check.key}\`, but its branch key \`${s.branchOn}\` is unmeasured: ${reasons}; the check reads a number nothing calibrated. To measure the route, ${fix}`, s, "check");
    } else if (worst === "unmeasured") {
      add("warning", "unmeasured_route", `router \`${router.name}\` branches on \`${s.branchOn}\`, which is unmeasured: ${reasons}; a probabilistic choice routes the run and nothing records how sure it was. To measure the route, ${fix}`, s, "branchOn");
    }
    for (const { producer, cls } of found) {
      if (cls !== "measured" || producer.s.kind === "decision") continue;
      const verdict = producer.s.kind === "execution"
        ? `script \`${producer.name}\` declares itself; legitimate when the code behind it is calibrated`
        : `client task \`${producer.name}\` declares itself; discouraged, because an agent cannot calibrate its own confidence. Prefer a decision step for the judgment`;
      add("info", "declared_confidence", `router \`${router.name}\` checks \`${s.check?.key}\`, a confidence ${verdict}`, s, "check.key");
    }
  }
}

/** A procedure with execution steps declares the environment its scripts need, and launches each script with the
 *  declared interpreter or one of the declared tools. */
function requires(draft: Draft, steps: R[], err: Err): void {
  const executions = steps.filter((r) => r.s.kind === "execution");
  if (executions.length === 0) return;
  if (!draft.requires) {
    err("missing_requires", `the procedure runs scripts (${executions.map((r) => `\`${r.name}\``).join(", ")}) but declares no \`requires\`; add a \`requires\` block naming the interpreter and its minimum version, the packages, and the tools the scripts need`, undefined, "requires");
    return;
  }
  const declared = new Set([draft.requires.interpreter.name, ...draft.requires.tools]);
  for (const r of executions) {
    const launcher = r.s.command?.[0] ?? DEFAULT_LAUNCHER;
    if (!declared.has(launcher)) {
      const how = r.s.command ? "is launched with" : "has no `command`, so it is launched with";
      err("undeclared_launcher", `execution step \`${r.name}\` ${how} \`${launcher}\`, which \`requires\` does not name; make it the interpreter or add it to \`tools\``, r.s, r.s.command ? "command[0]" : "command");
    }
  }
}

// ------------------------------------------------------------------------------------------ unfinished

function unfinished(d: Draft, options: LintOptions, add: Add): void {
  const todo = (code: string, message: string, step?: Step, field?: string) => add("unfinished", code, message, step, field);

  if (!d.purpose.trim()) todo("empty_purpose", "`purpose` is empty", undefined, "purpose");
  d.triggerWhen.forEach((t, i) => { if (!t.trim()) todo("empty_trigger_when", `\`trigger_when\` entry ${i + 1} is empty`, undefined, `triggerWhen[${i}]`); });

  const files = options.files ?? {};
  for (const s of d.steps) {
    const label = s.name ? `step \`${s.name}\`` : `an unnamed ${s.kind} step`;
    if (s.kind === "end") {
      if (s.inputs.length === 0) todo("end_without_inputs", `${label} declares no inputs, so the procedure returns nothing`, s, "inputs");
    } else if (s.kind !== "start" && !s.description.trim()) {
      todo("empty_description", `${label} has no description`, s, "description");
    }
    (s.questions ?? []).forEach((q, i) => {
      if (!q.instructions.trim()) todo("empty_instructions", `${label}: question \`${q.name}\` has no instructions`, s, `questions[${i}].instructions`);
    });
    if (s.kind === "execution" && s.command !== undefined && s.command[0] !== "python") {
      todo("non_python_launcher", `${label} is launched with \`${s.command[0] ?? ""}\`; Studio writes Python scripts only, so no stub is made for it`, s, "command");
    }
    const paths: [string | undefined, string][] = [
      [s.script, "script"], [s.template, "template"],
      ...(s.assets ?? []).map((a, i): [string, string] => [a, `assets[${i}]`]),
      ...(s.references ?? []).map((r, i): [string, string] => [r.path, `references[${i}].path`]),
    ];
    const seen = new Set<string>();
    for (const [path, field] of paths) {
      if (!path || seen.has(path)) continue;
      seen.add(path);
      if (files[path]?.includes(PLACEHOLDER_MARKER)) todo("placeholder_file", `${label}: \`${path}\` is still a placeholder`, s, field);
    }
  }
}

// ------------------------------------------------------------------------------------------ Studio-only rules

/** Rules aip-spec does not state but a graph builder needs (S5). Each code is listed in docs/studio-lint.md. All are
 *  warnings except `loop_without_router` (an error) and `branch_value_not_an_answer` (unfinished). */
function studio(d: Draft, add: Add): void {
  const warn = (code: string, message: string, step?: Step, field?: string) => add("warning", code, message, step, field);
  const label = (s: Step) => (s.name ? `step \`${s.name}\`` : `an unnamed ${s.kind} step`);
  const byId = new Map(d.steps.map((s) => [s.id, s]));
  const steps = resolve(d);
  const types = typeTable(steps);

  // A runnable chain that comes back to itself with no router on it can never leave.
  const reported = new Set<string>();
  for (const s of d.steps) {
    if (!RUNNABLE_KINDS.includes(s.kind) || reported.has(s.id)) continue;
    const chain: Step[] = [];
    let cur: Step | undefined = s;
    while (cur && RUNNABLE_KINDS.includes(cur.kind) && chain.length <= d.steps.length) {
      chain.push(cur);
      cur = cur.next ? byId.get(cur.next) : undefined;
      if (cur === s) {
        chain.forEach((c) => reported.add(c.id));
        const names = chain.map((c) => `\`${c.name || c.id}\``).join(" → ");
        add("error", "loop_without_router", `${names} → \`${s.name || s.id}\` is a loop with no router on it, so it can never leave; put a router in the loop with a branch that goes on`, s, "next");
        break;
      }
    }
  }

  for (const s of d.steps) {
    if (s.kind === "router") {
      // Two branches to the same step: one would do.
      const seen = new Map<string, string>();
      (s.branches ?? []).forEach((b, i) => {
        if (!b.target) return;
        const first = seen.get(b.target);
        if (first !== undefined) {
          const to = byId.get(b.target);
          warn("redundant_branches", `router ${label(s)}: the branches for \`${first}\` and \`${b.value}\` both go to \`${to ? to.name : b.target}\`; a router whose branches agree decides nothing there`, s, `branches[${i}].target`);
        } else seen.set(b.target, b.value);
      });

      // A branch value the key can never hold, when the key's producer is known but is not the decision feeding
      // the router (that case is aip-spec's `unknown_branch_value`).
      const k = s.branchOn;
      if (k) {
        const direct = d.steps.some((f) => f.kind === "decision" && f.next === s.id && (f.questions ?? []).some((q) => q.name === k));
        const q = d.steps.flatMap((x) => x.questions ?? []).find((x) => x.name === k);
        const allowed = q
          ? (q.type === "noul" ? ["true", "false"] : q.type === "choice" ? q.criteria.map((c) => c.label) : q.criteria.map((_, n) => String(n)))
          : types.get(k)?.[0] === "boolean" ? ["true", "false"] : undefined;
        if (!direct && allowed) {
          (s.branches ?? []).forEach((b, i) => {
            if (b.value && !allowed.includes(b.value)) {
              add("unfinished", "branch_value_not_an_answer", `router ${label(s)}: \`${k}\` is ${q ? `a ${q.type} question's answer` : "a boolean"}, so it is never \`${b.value}\`; its values are ${allowed.map((a) => `\`${a}\``).join(", ")}`, s, `branches[${i}].value`);
            }
          });
        }
      }
    }

    if (s.kind === "decision") {
      (s.questions ?? []).forEach((q, i) => {
        if (q.type === "choice") {
          const labels = q.criteria.map((c) => c.label).filter(Boolean);
          if (labels.length > 0 && labels.every((l) => /^-?[0-9]+(\.[0-9]+)?$/.test(l))) {
            warn("numeric_choice_labels", `${label(s)}: choice question \`${q.name}\` has only numbers as labels; if the answers are ordered, make it a score question, otherwise give the labels names`, s, `questions[${i}].criteria`);
          }
        }
        if (q.type === "score") {
          const levels = q.criteria.map((c) => c.trim());
          const dup = levels.find((l, j) => l && levels.indexOf(l) !== j);
          if (dup !== undefined) warn("duplicate_score_levels", `${label(s)}: score question \`${q.name}\` describes two levels as \`${dup}\`, so the rubric cannot tell them apart`, s, `questions[${i}].criteria`);
        }
      });
    }

    if (s.kind === "execution" && (s.outputs ?? []).length === 0) {
      warn("execution_without_outputs", `${label(s)} declares no outputs, so nothing after it can use what its script does`, s, "outputs");
    }
  }

  // An output nothing reads, where some step could read it: a dead key. A key produced on only some paths, which
  // no step after the paths join can take, is left alone; the author cannot fix that by adding an input. A router's
  // confidence check reads its key.
  const read = new Set(d.steps.flatMap((s) => (s.kind === "router" ? [s.branchOn, s.check?.key].filter((k): k is string => !!k) : s.inputs.map((i) => i.name))));
  const reachable = new Set([...availableKeys(d).values()].flatMap((keys) => keys.map((k) => k.name)));
  for (const s of d.steps) {
    if (s.kind !== "execution" && s.kind !== "client_task") continue;
    (s.outputs ?? []).forEach((o, i) => {
      if (o.name && !read.has(o.name) && reachable.has(o.name)) {
        warn("dead_key", `${label(s)} outputs \`${o.name}\`, which no step reads; add it to the inputs of the step that needs it (the end, if it is part of the result), or remove it`, s, `outputs[${i}].name`);
      }
    });
  }

  // A step and a key with one name read as each other in a trace.
  const keys = new Set(d.steps.flatMap((s) => [...s.inputs.map((i) => i.name), ...(s.outputs ?? []).map((o) => o.name), ...(s.questions ?? []).map((q) => q.name)]).filter(Boolean));
  for (const s of d.steps) {
    if (s.name && keys.has(s.name)) warn("name_collision", `${label(s)} has the same name as the key \`${s.name}\`; in a trace the step and the key read as each other, so rename one`, s, "name");
  }
}
