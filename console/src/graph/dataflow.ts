import type { ProcedureInfo } from "../api/types";

// Key-level data flow (format 0.8): a key goes from each step that produces it to every step that consumes it.
// The start step produces the procedure's inputs; execution and client_task steps produce their `outputs`; a
// decision produces one key per question and `<question>_confidence` for each question its `confidence` list
// names. A step consumes its `inputs`, a router its `branch_on` key and the key its confidence check reads.
// Routers and the end step add nothing to the state. A key may have several producers: where a run passes
// through more than one, the later one overwrites the value.

export interface DataEdge { key: string; from: string; to: string }

/** The state key a decision's `confidence` list emits for a question (aip-spec's fixed naming). */
export const confidenceKey = (question: string) => `${question}_confidence`;

/** Each key's producers, step names in step order. */
export function producers(info: ProcedureInfo): Map<string, string[]> {
  const out = new Map<string, string[]>();
  const add = (key: string, step: string) => { const list = out.get(key) ?? []; if (!list.includes(step)) list.push(step); out.set(key, list); };
  for (const step of [...info.step_details].sort((a, b) => a.order - b.order)) for (const key of outputsOf(info, step.name)) add(key, step.name);
  return out;
}

/** The keys a step adds to the state, in declaration order. */
export function outputsOf(info: ProcedureInfo, step: string): string[] {
  const detail = info.step_details.find((s) => s.name === step);
  if (detail?.kind === "start") return info.inputs.filter((i) => i.step === step).map((i) => i.name);
  if (detail?.kind === "decision") {
    const questions = info.questions.filter((q) => q.step === step);
    return [...questions.map((q) => q.name), ...questions.filter((q) => q.confidence).map((q) => confidenceKey(q.name))];
  }
  return (info.outputs ?? []).filter((o) => o.step === step).map((o) => o.name);
}

/** The keys a step reads from the state, in declaration order. */
export function inputsOf(info: ProcedureInfo, step: string): string[] {
  const detail = info.step_details.find((s) => s.name === step);
  if (detail?.kind === "start") return [];
  if (detail?.kind === "router") return [...(detail.branch_on ? [detail.branch_on] : []), ...(detail.check?.key ? [detail.check.key] : [])];
  return info.inputs.filter((i) => i.step === step).map((i) => i.name);
}

/** One edge per (key, producer, consumer), in step order. A key with no producer (an invalid skill) is left out. */
export function dataFlow(info: ProcedureInfo): DataEdge[] {
  const from = producers(info);
  const edges: DataEdge[] = [];
  for (const step of [...info.step_details].sort((a, b) => a.order - b.order)) {
    for (const key of inputsOf(info, step.name)) {
      for (const producer of from.get(key) ?? []) if (producer !== step.name) edges.push({ key, from: producer, to: step.name });
    }
  }
  return edges;
}

/** The edges grouped per (producer, consumer) pair, keys in order: what the graph draws as one arrow. */
export function groupFlow(edges: DataEdge[]): { from: string; to: string; keys: string[] }[] {
  const groups = new Map<string, { from: string; to: string; keys: string[] }>();
  for (const e of edges) {
    const id = `${e.from}->${e.to}`;
    const g = groups.get(id) ?? { from: e.from, to: e.to, keys: [] };
    if (!g.keys.includes(e.key)) g.keys.push(e.key);
    groups.set(id, g);
  }
  return [...groups.values()];
}
