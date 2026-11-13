// The steps a person may answer when the model drives a run (plan C6): the run console lists a procedure's
// Task_Agent steps, and the ones the user ticks pause for the page while the model answers the rest. Nothing is
// ticked to begin with: which steps are a person's is the user's to say, per run, not a rule of aip's or of this
// page. No DOM, no imports but types: it runs under node as it is (test/human.test.ts).

import type { Graph } from "../graph/bundle.ts";

/** A Task_Agent step of a procedure. */
export interface AgentStep { name: string; description: string }

const text = (v: unknown) => (typeof v === "string" ? v : "");

/** The Task_Agent steps of a bundle's graph, in written order. */
export function agentSteps(graph: Graph): AgentStep[] {
  return graph.nodes
    .filter((n) => n.labels.includes("Step") && n.properties.kind === "Task_Agent")
    .sort((a, b) => Number(a.properties.line ?? 0) - Number(b.properties.line ?? 0))
    .map((n) => ({ name: text(n.properties.name), description: text(n.properties.description) }));
}
