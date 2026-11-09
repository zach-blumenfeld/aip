// Edits of a Draft's graph that keep it connected, as the Studio's buttons make them. Each takes a Draft and
// returns a changed copy; none can leave a step with a second outbound edge, since an edge is a field (`next`, a
// router's branches), not a list.

import { RUNNABLE_KINDS, confidenceKey, newStepId, startOf, type Branch, type Draft, type Step, type StepKind } from "./draft";
import { groupFlow, type DataEdge } from "../graph/dataflow";
import type { Edge, Branch as GraphBranch, StepDetail } from "../api/types";

/** The kinds a step can be added as, after another: every kind but `start`, which a draft has exactly one of. */
export const KINDS: StepKind[] = ["decision", "execution", "client_task", "router", "end"];

/** A step name not yet taken, from its kind: `client-task-2`. The `start` and `end` steps are plainly `start` and
 *  `end` when they can be. */
function freshName(kind: StepKind, steps: Step[]): string {
  const taken = new Set(steps.map((s) => s.name));
  const base = kind === "client_task" ? "client-task" : kind;
  if ((kind === "end" || kind === "start") && !taken.has(base)) return base;
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
  return step;
}

/** The steps whose outbound edge reaches `id`: by `next`, the router branches that target it, and the router
 *  confidence checks that send the run to it. */
function pointingAt(d: Draft, id: string): { steps: Step[]; branches: Branch[]; checks: Step[] } {
  return {
    steps: d.steps.filter((s) => s.next === id),
    branches: d.steps.flatMap((s) => s.branches ?? []).filter((b) => b.target === id),
    checks: d.steps.filter((s) => s.check?.to === id),
  };
}

/** The runnable steps no edge (a `next`, a branch, a check's `to`) reaches: what a start step is missing a hand-off
 *  to, in step order. */
export function unreachedRunnable(d: Draft): Step[] {
  const reached = new Set<string>();
  for (const s of d.steps) {
    if (s.next) reached.add(s.next);
    for (const b of s.branches ?? []) if (b.target) reached.add(b.target);
    if (s.check?.to) reached.add(s.check.to);
  }
  return d.steps.filter((s) => RUNNABLE_KINDS.includes(s.kind) && !reached.has(s.id));
}

/** The runnable step a start step should hand to when nothing says: the first one no edge reaches, else the first
 *  runnable step. Undefined when the draft has none. */
function firstRunnable(d: Draft): Step | undefined {
  return unreachedRunnable(d)[0] ?? d.steps.find((s) => RUNNABLE_KINDS.includes(s.kind));
}

/** Add the `start` step to a draft that has none, first in order, handing to the first runnable step nothing
 *  reaches. A draft that already has one is returned unchanged. Returns the Draft and the start's id. */
export function addStart(d: Draft): { draft: Draft; id: string } {
  const out = structuredClone(d);
  const have = startOf(out.steps);
  if (have) return { draft: out, id: have.id };
  const start = newStep("start", out.steps);
  start.next = firstRunnable(out)?.id;
  out.steps.unshift(start);
  return { draft: out, id: start.id };
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
 *  With no `afterId` the step is appended; a draft with no `start` step gets one first, handing to the new step,
 *  so "the first step" of an empty draft is the start and the step it names. A router takes a new step as a new
 *  branch. */
export function addStepAfter(d: Draft, afterId: string | undefined, kind: StepKind): { draft: Draft; id: string } {
  let out = structuredClone(d);
  const at = afterId === undefined ? -1 : out.steps.findIndex((s) => s.id === afterId);
  if (at < 0) {
    if (!startOf(out.steps) && kind !== "start") {
      out = addStart(out).draft;
      const start = startOf(out.steps)!;
      const step = newStep(kind, out.steps);
      out.steps.splice(out.steps.indexOf(start) + 1, 0, step);
      if (start.next === undefined) start.next = step.id;
      return { draft: out, id: step.id };
    }
    const step = newStep(kind, out.steps);
    out.steps.push(step);
    return { draft: out, id: step.id };
  }
  const step = newStep(kind, out.steps);
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

/** Remove a step. What pointed at it (a `next`, a branch, a check's `to`) points at its successor when it has exactly
 *  one; otherwise the edges are left dangling (unset) for the linter to report. Removing the start step leaves the
 *  draft without one, which the linter reports and `addStart` fixes. */
export function deleteStep(d: Draft, id: string): Draft {
  const out = structuredClone(d);
  const at = out.steps.findIndex((s) => s.id === id);
  if (at < 0) return out;
  const successor = onlySuccessor(out.steps[at]);
  const into = pointingAt(out, id);
  for (const s of into.steps) s.next = successor;
  for (const b of into.branches) b.target = successor;
  for (const s of into.checks) s.check!.to = successor;
  out.steps.splice(at, 1);
  return out;
}

/** Make a runnable step the first one: the start step hands to it, and it follows the start in order. The step
 *  the start handed to before keeps its place; if nothing else reaches it, the linter says so. */
export function setStart(d: Draft, id: string): Draft {
  const out = structuredClone(d);
  const start = startOf(out.steps);
  const at = out.steps.findIndex((s) => s.id === id);
  if (!start || at < 0 || !RUNNABLE_KINDS.includes(out.steps[at].kind)) return out;
  start.next = id;
  const [step] = out.steps.splice(at, 1);
  out.steps.splice(out.steps.indexOf(start) + 1, 0, step);
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
    steps, edges, branches, start: startOf(d.steps)?.id ?? "", end: d.steps.find((s) => s.kind === "end")?.id ?? "",
    labels: new Map(d.steps.map((s) => [s.id, label(s)])),
  };
}

// ------------------------------------------------------------------------------------------------ data flow

/** The keys a step adds to the state: the start step its inputs, a decision its question names and the confidence
 *  keys it emits, an execution or client task its outputs. */
export function producedBy(s: Step): string[] {
  if (s.kind === "start") return s.inputs.map((i) => i.name).filter(Boolean);
  if (s.kind === "decision") {
    return [...(s.questions ?? []).map((q) => q.name), ...(s.confidence ?? []).filter(Boolean).map(confidenceKey)].filter(Boolean);
  }
  return (s.outputs ?? []).map((o) => o.name).filter(Boolean);
}

/** The keys a step reads from the state: a router its branch key and the key its check reads, the start nothing,
 *  every other step its inputs. */
export function consumedBy(s: Step): string[] {
  if (s.kind === "start") return [];
  if (s.kind === "router") return [...(s.branchOn ? [s.branchOn] : []), ...(s.check?.key ? [s.check.key] : [])];
  return s.inputs.map((i) => i.name).filter(Boolean);
}

/** The state keys as arrows for StepGraph's data view: one per (producer, consumer) pair, keyed by step id. The
 *  start step produces its inputs; a key with several producers gets an arrow from each. A key nothing produces
 *  has no arrow (the linter says so). */
export function flowOf(d: Draft): { from: string; to: string; keys: string[] }[] {
  const producers = new Map<string, string[]>();
  for (const s of d.steps) for (const key of producedBy(s)) producers.set(key, [...(producers.get(key) ?? []), s.id]);
  const edges: DataEdge[] = [];
  for (const s of d.steps) {
    for (const key of consumedBy(s)) {
      for (const from of producers.get(key) ?? []) if (from !== s.id) edges.push({ key, from, to: s.id });
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

/** Declare a key as something the client supplies: an input of the start step. A draft with no start step is
 *  returned unchanged (the linter says so, and `addStart` fixes it). */
export function declareStartInput(d: Draft, key: string, type: string): Draft {
  const out = structuredClone(d);
  const start = startOf(out.steps);
  if (start && !start.inputs.some((i) => i.name === key)) start.inputs.push({ name: key, type });
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
