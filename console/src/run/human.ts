// Which tasks a person answers when a run goes ahead with `aip runah` (plans C5 and R8): the run console lists a
// procedure's Task_Agent steps as the human-step picker (`--human`) and ticks the ones written for a person. Which
// those are is aip's rule, in one place (`aip.model.answerer.human_steps`, the same steps `aip runah` stops at with
// no `--human`); the page reads its answer off the procedure's description (`human_steps`, `aip info --json`) and
// keeps no rule of its own. No DOM, no imports but types: it runs under node as it is (test/human.test.ts).

import type { Graph } from "../graph/bundle.ts";

/** A Task_Agent step of a procedure, and whether aip says a person answers it. */
export interface AgentStep { name: string; description: string; person: boolean }

const text = (v: unknown) => (typeof v === "string" ? v : "");

/** The Task_Agent steps of a bundle's graph, in written order, each a person's when `marked` (the description's
 *  `human_steps`) names it. */
export function agentSteps(graph: Graph, marked: readonly string[] = []): AgentStep[] {
  return graph.nodes
    .filter((n) => n.labels.includes("Step") && n.properties.kind === "Task_Agent")
    .sort((a, b) => Number(a.properties.line ?? 0) - Number(b.properties.line ?? 0))
    .map((n) => {
      const name = text(n.properties.name);
      return { name, description: text(n.properties.description), person: marked.includes(name) };
    });
}
