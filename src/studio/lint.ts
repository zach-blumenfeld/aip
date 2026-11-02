// The Studio's linter: a TypeScript port of aip-spec's frontmatter, schema, graph and state rules (`skill.py`,
// `models.py`), run on a Draft in the browser on every edit. Codes are aip-spec's where one exists; the models'
// pattern and length rules are all `schema_violation`, as there. The real `aip-spec validate` stays the authority:
// e2e/lint-parity.spec.ts runs both over the same fixtures and fails on any disagreement in the error codes.
//
// Three tiers. `error`: aip-spec would reject it. `unfinished`: valid or fixable, but a placeholder or an empty
// field a template may carry. `warning`: reserved for Studio-only advice (S5).

import { QUESTION_TYPES, RUNNABLE_KINDS, UNRESOLVED, type Draft, type Step } from "./draft";

export type Tier = "error" | "unfinished" | "warning";

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

/** A step with its edges resolved to names, the form aip-spec's checks work on. */
interface R {
  s: Step;
  index: number;
  name: string;
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
  if (draft.steps.length > 0) graph(draft, err);
  unfinished(draft, options, add);
  if (draft.steps.length > 0) studio(draft, add);
  return issues;
}

/** Error codes only the Studio reports. Each one comes with an aip-spec error on the same draft (docs/studio-lint.md),
 *  so the parity test leaves them out of the comparison. */
export const STUDIO_ONLY_ERRORS = new Set(["loop_without_router"]);

// ------------------------------------------------------------------------------------------ frontmatter

type Err = (code: string, message: string, step?: Step, field?: string, key?: string) => void;

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

  if (d.steps.length < 2) bad(`\`steps\` needs at least 2 steps (a runnable step and an end); there ${d.steps.length === 1 ? "is 1" : `are ${d.steps.length}`}`, undefined, "steps");
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
    if (!(RUNNABLE_KINDS as readonly string[]).includes(s.kind) && s.kind !== "router" && s.kind !== "end") {
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

    if (s.kind !== "router" && s.kind !== "end" && s.next === undefined) bad(`${label(s)} has no next step (\`inputs_to\`); every runnable step names the step that receives its output`, s, "next");

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
      for (const [key, value] of Object.entries(s.thresholds ?? {})) {
        if (!(value >= 0 && value <= 1)) bad(`${label(s)}: threshold \`${key}\` must be between 0 and 1; got ${value}`, s, `thresholds.${key}`);
      }
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
    const targets = s.kind === "router" ? (s.branches ?? []).map((b) => nameOf(b.target)) : [nameOf(s.next)];
    return { s, index, name: s.name, targets: targets.filter((t): t is string => t !== undefined), inputsTo: s.kind === "router" || s.kind === "end" ? undefined : nameOf(s.next) };
  });
}

const consumed = (r: R): string[] => (r.s.kind === "router" ? (r.s.branchOn ? [r.s.branchOn] : []) : r.s.inputs.map((i) => i.name).filter(Boolean));

const produced = (r: R): string[] =>
  r.s.kind === "decision" ? (r.s.questions ?? []).map((q) => q.name).filter(Boolean) : (r.s.outputs ?? []).map((i) => i.name).filter(Boolean);

function graph(draft: Draft, err: Err): void {
  const steps = resolve(draft);
  const start = steps[0];
  const byName = new Map<string, R>();
  for (const r of steps) {
    if (byName.has(r.name)) {
      if (r.name) err("duplicate_step_name", `step name \`${r.name}\` is declared more than once`, r.s, "name");
    } else byName.set(r.name, r);
  }

  if (!(RUNNABLE_KINDS as readonly string[]).includes(start.s.kind)) {
    err("invalid_start_step", `the first step is the start and must be a decision, execution, or client_task; got kind \`${start.s.kind}\``, start.s, "kind");
  }

  const ends = steps.filter((r) => r.s.kind === "end");
  if (ends.length === 0) err("missing_end_step", "procedure has no step of kind `end`", undefined, "steps");
  else if (ends.length > 1) err("multiple_end_steps", `procedure must have exactly one \`end\` step; found [${ends.map((r) => `'${r.name}'`).join(", ")}]`, undefined, "steps");

  for (const r of steps) {
    for (const target of r.targets) {
      if (!byName.has(target)) {
        err("unknown_step_reference", `step \`${r.name}\` hands off to \`${target}\`, which is not a declared step`, r.s, r.s.kind === "router" ? "branches" : "next");
      }
    }
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

  const fromStart = reachable(start.name);
  for (const r of steps) {
    if (!fromStart.has(r.name)) err("unreachable_step", `step \`${r.name}\` cannot be reached from the start step \`${start.name}\``, r.s);
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

  state(steps, byName, err);
  requires(draft, steps, err);

  for (const r of steps) {
    const seen = new Set<string>();
    r.s.inputs.forEach((item, j) => {
      if (r.s.kind === "router") return;
      if (seen.has(item.name)) err("duplicate_input_name", `step \`${r.name}\` declares input \`${item.name}\` more than once`, r.s, `inputs[${j}].name`);
      seen.add(item.name);
    });
    if (r.s.kind === "decision") {
      const names = new Set((r.s.questions ?? []).map((q) => q.name));
      for (const key of Object.keys(r.s.thresholds ?? {})) {
        if (!names.has(key)) err("unknown_threshold_question", `step \`${r.name}\` sets a threshold for \`${key}\`, which is not one of its questions`, r.s, `thresholds.${key}`);
      }
    }
  }
}

/** The state contract. A literal port of aip-spec's `check_state`: every consumed key has a producer on every path to
 *  its consumer (or is a start input), every key has one producer, client tasks declare outputs, and a consumer
 *  declares the type its producer does. */
function state(steps: R[], byName: Map<string, R>, err: Err): void {
  const start = steps[0];
  const startInputs = new Set(start.s.kind !== "router" ? consumed(start) : []);

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

  // Rule 2: one producer per key, never a start input.
  const producers = new Map<string, R[]>();
  for (const r of steps) for (const key of unique(produced(r))) producers.set(key, [...(producers.get(key) ?? []), r]);
  for (const [key, makers] of producers) {
    const names = makers.map((m) => `\`${m.name}\``).join(", ");
    if (makers.length > 1) {
      err("duplicate_producer", `key \`${key}\` is produced by ${names}; each key must have exactly one producer, so rename one of them`, makers[1].s);
    }
    if (startInputs.has(key)) {
      err("duplicate_producer", `key \`${key}\` is a start input (declared on \`${start.name}\`) and is also produced by ${names}; a step must not overwrite what the client supplied, so rename the output`, makers[0].s);
    }
  }

  // Rule 4: a consumer declares the type its producer declares. One key, one type, end to end.
  const producedType = typeTable(steps);
  for (const r of steps) {
    if (r.s.kind === "router") continue;
    r.s.inputs.forEach((item, j) => {
      if (r === start && startInputs.has(item.name)) return;
      const expected = producedType.get(item.name);
      if (expected && expected[0] !== item.type) {
        err("type_mismatch", `step \`${r.name}\` declares input \`${item.name}\` as \`${item.type}\`, but it is \`${expected[0]}\` (${expected[1]}); a key has one type everywhere it is declared`, r.s, `inputs[${j}].type`);
      }
    });
  }

  // Rule 1: keys available on every path (must-availability over the graph, cycles included).
  const available = mustAvailable(steps, byName, startInputs);
  for (const r of steps) {
    const have = available.get(r.name);
    if (have == null) continue;                    // unreachable; reported elsewhere
    for (const k of unique(consumed(r)).filter((k) => !have.has(k))) {
      if (r.s.kind === "router") {
        err("unproduced_input", `router \`${r.name}\` branches on \`${k}\`, which no step produces on every path to it; pick a key that reaches the router, or declare \`${k}\` on the start step \`${start.name}\` or as an \`output\` of an upstream step`, r.s, "branchOn", k);
        continue;
      }
      err("unproduced_input", `step \`${r.name}\` consumes \`${k}\`, which no step produces on every path to it; declare it on the start step \`${start.name}\` if the client supplies it, or as an \`output\` of an upstream step`, r.s, "inputs", k);
    }
  }
}

/** Each key's type and where it comes from, first declaration winning: start inputs, then each step in order. */
function typeTable(steps: R[]): Map<string, [string, string]> {
  const start = steps[0];
  const table = new Map<string, [string, string]>();
  const setDefault = (key: string, value: [string, string]) => { if (!table.has(key)) table.set(key, value); };
  if (start.s.kind !== "router") for (const item of start.s.inputs) setDefault(item.name, [item.type, `start input on \`${start.name}\``]);
  for (const r of steps) {
    if (r.s.kind === "decision") for (const q of r.s.questions ?? []) setDefault(q.name, [QUESTION_TYPES[q.type] ?? q.type, `a ${q.type} question in \`${r.name}\``]);
    for (const item of r.s.outputs ?? []) setDefault(item.name, [item.type, `output of \`${r.name}\``]);
  }
  return table;
}

/** The keys in the state when each step starts, on every path to it (null: no path from the start found). A
 *  fixed point over the graph, so a loop is handled. */
function mustAvailable(steps: R[], byName: Map<string, R>, startInputs: Set<string>): Map<string, Set<string> | null> {
  const start = steps[0];
  const available = new Map<string, Set<string> | null>(steps.map((r) => [r.name, null]));
  available.set(start.name, new Set(startInputs));
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
      const next = known.reduce((a, b) => new Set([...a].filter((k) => b.has(k))));
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

/** For each step id, the keys it may declare as inputs: the start inputs and everything produced on every path to
 *  it, with their types. The same computation `unproduced_input` is judged by, so a pick from this list never
 *  raises it. A step nothing reaches has none. */
export function availableKeys(draft: Draft): Map<string, AvailableKey[]> {
  const out = new Map<string, AvailableKey[]>();
  if (draft.steps.length === 0) return out;
  const steps = resolve(draft);
  const byName = new Map<string, R>();
  for (const r of steps) if (!byName.has(r.name)) byName.set(r.name, r);
  const start = steps[0];
  const available = mustAvailable(steps, byName, new Set(start.s.kind !== "router" ? consumed(start) : []));
  const types = typeTable(steps);
  for (const r of steps) {
    const have = byName.get(r.name) === r ? available.get(r.name) : null;
    out.set(r.s.id, have ? [...have].map((name) => ({ name, type: types.get(name)?.[0] ?? "string" })) : []);
  }
  return out;
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

type Add = (tier: Tier, code: string, message: string, step?: Step, field?: string) => void;

function unfinished(d: Draft, options: LintOptions, add: Add): void {
  const todo = (code: string, message: string, step?: Step, field?: string) => add("unfinished", code, message, step, field);

  if (!d.purpose.trim()) todo("empty_purpose", "`purpose` is empty", undefined, "purpose");
  d.triggerWhen.forEach((t, i) => { if (!t.trim()) todo("empty_trigger_when", `\`trigger_when\` entry ${i + 1} is empty`, undefined, `triggerWhen[${i}]`); });

  const files = options.files ?? {};
  for (const s of d.steps) {
    const label = s.name ? `step \`${s.name}\`` : `an unnamed ${s.kind} step`;
    if (s.kind === "end") {
      if (s.inputs.length === 0) todo("end_without_inputs", `${label} declares no inputs, so the procedure returns nothing`, s, "inputs");
    } else if (!s.description.trim()) {
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
    if (!(RUNNABLE_KINDS as readonly string[]).includes(s.kind) || reported.has(s.id)) continue;
    const chain: Step[] = [];
    let cur: Step | undefined = s;
    while (cur && (RUNNABLE_KINDS as readonly string[]).includes(cur.kind) && chain.length <= d.steps.length) {
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
      const questions = s.questions ?? [];
      if (questions.length > 0 && Object.keys(s.thresholds ?? {}).length === 0) {
        warn("no_thresholds", `${label(s)} sets no review threshold, so no answer is ever flagged for the calling agent to check; set one on the questions where a wrong answer costs most`, s, "questions");
      }
      questions.forEach((q, i) => {
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
  // no step after the paths join can take, is left alone; the author cannot fix that by adding an input.
  const read = new Set(d.steps.flatMap((s) => (s.kind === "router" ? (s.branchOn ? [s.branchOn] : []) : s.inputs.map((i) => i.name))));
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
