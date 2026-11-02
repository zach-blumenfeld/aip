// Edits of a Draft's graph that keep it connected, as the Studio's buttons make them. Each takes a Draft and
// returns a changed copy; none can leave a step with a second outbound edge, since an edge is a field (`next`, a
// router's branches), not a list.

import { RUNNABLE_KINDS, newStepId, type Branch, type Draft, type Step, type StepKind } from "./draft";
import { START_INPUT, groupFlow, type DataEdge } from "../graph/dataflow";
import type { Edge, Branch as GraphBranch, StepDetail } from "../api/types";

export const KINDS: StepKind[] = ["decision", "execution", "client_task", "router", "end"];

/** A step name not yet taken, from its kind: `client-task-2`. The `end` step is plainly `end` when it can be. */
function freshName(kind: StepKind, steps: Step[]): string {
  const taken = new Set(steps.map((s) => s.name));
  const base = kind === "client_task" ? "client-task" : kind;
  if (kind === "end" && !taken.has(base)) return base;
  let n = 1;
  while (taken.has(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}

export function newStep(kind: StepKind, steps: Step[]): Step {
  const name = freshName(kind, steps);
  const step: Step = { id: newStepId(steps.map((s) => s.id)), kind, name, description: "", inputs: [] };
  if (kind === "decision") step.questions = [];
  if (kind === "execution") { step.script = `scripts/${name}.py`; step.outputs = []; }
  if (kind === "client_task") { step.template = `assets/${name}.md`; step.outputs = []; }
  if (kind === "router") step.branches = [];
  if (kind === "end") step.inputs = [];
  return step;
}

/** The steps whose outbound edge reaches `id`: by `next`, and the router branches that target it. */
function pointingAt(d: Draft, id: string): { steps: Step[]; branches: Branch[] } {
  return {
    steps: d.steps.filter((s) => s.next === id),
    branches: d.steps.flatMap((s) => s.branches ?? []).filter((b) => b.target === id),
  };
}

/** The one step this one leads to, when it has exactly one: `next`, or a router's single distinct target. */
export function onlySuccessor(s: Step): string | undefined {
  if (s.kind === "router") {
    const targets = new Set((s.branches ?? []).map((b) => b.target).filter((t): t is string => !!t));
    return targets.size === 1 ? [...targets][0] : undefined;
  }
  return s.next;
}

/** The decision that feeds a router and the choice/noul question its `branch_on` names (or, with it unset, the
 *  first such question), so the branch rows can start from the question's labels. */
function feeder(d: Draft, router: Step): { branchOn: string; values: string[] } | undefined {
  const decision = d.steps.find((s) => s.kind === "decision" && s.next === router.id);
  const questions = (decision?.questions ?? []).filter((q) => q.type !== "score");
  const q = questions.find((x) => x.name === router.branchOn) ?? (router.branchOn ? undefined : questions[0]);
  if (!q) return undefined;
  const values = q.type === "choice" ? q.criteria.map((c) => c.label) : ["true", "false"];
  return { branchOn: q.name, values };
}

/** Rows for the router from its feeding decision's question, keeping the targets of rows that already carry a value. */
export function prefillBranches(d: Draft, routerId: string): Draft {
  const out = structuredClone(d);
  const router = out.steps.find((s) => s.id === routerId);
  const f = router && feeder(out, router);
  if (!router || !f) return out;
  const old = router.branches ?? [];
  const spare = old.filter((b) => !b.value && b.target).map((b) => b.target);
  router.branchOn = f.branchOn;
  router.branches = f.values.map((value) => ({ value, target: old.find((b) => b.value === value)?.target ?? spare.shift() }));
  return out;
}

/** Add a step of `kind` after `afterId`, between it and what it led to. Returns the Draft and the new step's id.
 *  With no `afterId` the step is appended; a router takes it as a new branch. */
export function addStepAfter(d: Draft, afterId: string | undefined, kind: StepKind): { draft: Draft; id: string } {
  const out = structuredClone(d);
  const step = newStep(kind, out.steps);
  const at = afterId === undefined ? -1 : out.steps.findIndex((s) => s.id === afterId);
  if (at < 0) {
    // The start must be runnable; a first step of another kind is the author's to fix, the linter says so.
    out.steps.push(step);
    return { draft: out, id: step.id };
  }
  const after = out.steps[at];
  out.steps.splice(at + 1, 0, step);
  let old: string | undefined;
  if (after.kind === "router") {
    const branches = (after.branches ??= []);
    const open = branches.find((b) => !b.target);
    if (open) open.target = step.id; else branches.push({ value: "", target: step.id });
  } else if (after.kind !== "end") {
    old = after.next;
    after.next = step.id;
  }
  if (old !== undefined) {
    // The new step takes over where the old edge went, so the chain stays connected.
    if (step.kind === "router") step.branches = [{ value: "", target: old }, { value: "" }];
    else if (step.kind !== "end") step.next = old;
  }
  if (step.kind === "router") {
    const branches = (step.branches ??= []);
    while (branches.length < 2) branches.push({ value: "" });
    return { draft: prefillBranches(out, step.id), id: step.id };
  }
  return { draft: out, id: step.id };
}

/** Make a step of `kind` the target of one branch row of a router. A step the row already led to follows it, as
 *  with a splice, so nothing is cut off. Returns the Draft and the new step's id. */
export function addStepOnBranch(d: Draft, routerId: string, index: number, kind: StepKind): { draft: Draft; id: string } {
  const out = structuredClone(d);
  const router = out.steps.find((s) => s.id === routerId);
  const row = router?.branches?.[index];
  if (!router || !row) return { draft: out, id: routerId };
  const step = newStep(kind, out.steps);
  const old = row.target;
  out.steps.splice(out.steps.indexOf(router) + 1, 0, step);
  row.target = step.id;
  if (old !== undefined) {
    if (kind === "router") step.branches = [{ value: "", target: old }, { value: "" }];
    else if (kind !== "end") step.next = old;
  }
  if (kind === "router") {
    while ((step.branches ??= []).length < 2) step.branches.push({ value: "" });
    return { draft: prefillBranches(out, step.id), id: step.id };
  }
  return { draft: out, id: step.id };
}

/** Rename a step in place. A script or template path still at the default for the old name follows the new one, so
 *  its placeholder moves with it; a path the author chose is left alone. */
export function renameStep(s: Step, name: string): void {
  if (s.script === `scripts/${s.name}.py`) s.script = `scripts/${name}.py`;
  if (s.template === `assets/${s.name}.md`) s.template = `assets/${name}.md`;
  s.name = name;
}

/** Remove a step. What pointed at it points at its successor when it has exactly one; otherwise the edges are
 *  left dangling (unset) for the linter to report. Removing the start makes the successor the start. */
export function deleteStep(d: Draft, id: string): Draft {
  const out = structuredClone(d);
  const at = out.steps.findIndex((s) => s.id === id);
  if (at < 0) return out;
  const successor = onlySuccessor(out.steps[at]);
  const into = pointingAt(out, id);
  for (const s of into.steps) s.next = successor;
  for (const b of into.branches) b.target = successor;
  out.steps.splice(at, 1);
  if (at === 0 && successor) {
    const i = out.steps.findIndex((s) => s.id === successor);
    if (i > 0) out.steps.unshift(...out.steps.splice(i, 1));
  }
  return out;
}

/** Make a runnable step the start, which is the first step. */
export function setStart(d: Draft, id: string): Draft {
  const out = structuredClone(d);
  const at = out.steps.findIndex((s) => s.id === id);
  if (at <= 0 || !RUNNABLE_KINDS.includes(out.steps[at].kind)) return out;
  out.steps.unshift(...out.steps.splice(at, 1));
  return out;
}

/** Retarget a step's name for display: a step with no name yet shows its id. */
export const label = (s: Step) => s.name || `(${s.id})`;

/** The Draft as the shapes StepGraph draws: nodes keyed by step id, so a rename or a duplicate name moves nothing.
 *  An edge to a step that does not exist is not drawn. */
export function graphOf(d: Draft): { steps: StepDetail[]; edges: Edge[]; branches: GraphBranch[]; start: string; end: string; labels: Map<string, string> } {
  const ids = new Set(d.steps.map((s) => s.id));
  const steps: StepDetail[] = d.steps.map((s, order) => ({ name: s.id, kind: s.kind, order, description: s.description || null }));
  const edges: Edge[] = [];
  const branches: GraphBranch[] = [];
  for (const s of d.steps) {
    if (s.kind === "router") {
      for (const b of s.branches ?? []) if (b.target && ids.has(b.target)) branches.push({ router: s.id, value: b.value, to: b.target });
    } else if (s.next && ids.has(s.next)) edges.push({ from: s.id, to: s.next });
  }
  return {
    steps, edges, branches, start: d.steps[0]?.id ?? "", end: d.steps.find((s) => s.kind === "end")?.id ?? "",
    labels: new Map(d.steps.map((s) => [s.id, label(s)])),
  };
}

// ------------------------------------------------------------------------------------------------ data flow

/** The state keys as arrows for StepGraph's data view: one per (producer, consumer) pair, keyed by step id, the
 *  start input standing for what the client supplies. A key nothing produces has no arrow (the linter says so). */
export function flowOf(d: Draft): { from: string; to: string; keys: string[] }[] {
  const producer = new Map<string, string>();
  const start = d.steps[0];
  if (start && start.kind !== "router") for (const i of start.inputs) if (i.name) producer.set(i.name, START_INPUT);
  for (const s of d.steps) {
    if (s.kind === "decision") for (const q of s.questions ?? []) if (q.name && !producer.has(q.name)) producer.set(q.name, s.id);
    for (const o of s.outputs ?? []) if (o.name && !producer.has(o.name)) producer.set(o.name, s.id);
  }
  const edges: DataEdge[] = [];
  for (const s of d.steps) {
    const keys = s.kind === "router" ? (s.branchOn ? [s.branchOn] : []) : s.inputs.map((i) => i.name).filter(Boolean);
    for (const key of keys) {
      const from = producer.get(key);
      if (from !== undefined && !(s === start && from === START_INPUT)) edges.push({ key, from, to: s.id });
    }
  }
  return groupFlow(edges);
}

/** What a key's value can be, when the question that produces it is a choice, noul or score: the answers a router
 *  on it can branch over. Undefined for a key anything else produces. */
export function possibleValues(d: Draft, key: string): string[] | undefined {
  for (const s of d.steps) {
    const q = (s.questions ?? []).find((x) => x.name === key);
    if (!q) continue;
    if (q.type === "noul") return ["true", "false"];
    if (q.type === "choice") return q.criteria.map((c) => c.label).filter(Boolean);
    return q.criteria.map((_, n) => String(n));
  }
  return undefined;
}

// ------------------------------------------------------------------------------------------------ quick fixes

/** Declare a key as something the client supplies: an input of the start step. */
export function declareStartInput(d: Draft, key: string, type: string): Draft {
  const out = structuredClone(d);
  const start = out.steps[0];
  if (start && start.kind !== "router" && !start.inputs.some((i) => i.name === key)) start.inputs.push({ name: key, type });
  return out;
}

/** Declare a key as an output of an execution or client_task step. */
export function declareOutput(d: Draft, stepId: string, key: string, type: string): Draft {
  const out = structuredClone(d);
  const step = out.steps.find((s) => s.id === stepId);
  if (step && (step.kind === "execution" || step.kind === "client_task") && !(step.outputs ?? []).some((o) => o.name === key)) {
    (step.outputs ??= []).push({ name: key, type });
  }
  return out;
}
