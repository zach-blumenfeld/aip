// Which tasks a person answers when a run goes ahead with `aip runah` (plan C5): the run console lists a
// procedure's Task_Agent steps as the human-step picker (`--human`) and ticks the ones written for a
// person. A step is for a person when its prompt begins with the drafter's marker (build_procedure's and
// edit_procedure's prompts write it) or its description says a person does it. No DOM, no imports but
// types: it runs under node as it is (test/human.test.ts).

import type { Graph } from "../graph/bundle.ts";

/** How build_procedure and edit_procedure open a task for a person (their assets/draft.md and rewrite.md). */
export const PERSON_MARKER = "This is a task for a person, not for you";

/** A Task_Agent step of a procedure, with its prompt (the Prompt file's text, or the description when it has none). */
export interface AgentStep { name: string; description: string; prompt: string; person: boolean }

/** Whether a task is a person's: its prompt opens with the marker, or its description names a person doing it. */
export function forAPerson(description: string, prompt: string): boolean {
  const opens = (text: string) => text.trim().toLowerCase().startsWith(PERSON_MARKER.toLowerCase());
  return opens(prompt) || opens(description) || /\b(a|the) (person|human)\b/i.test(description);
}

const text = (v: unknown) => (typeof v === "string" ? v : "");

/** The Task_Agent steps of a bundle's graph, in written order, each with whether a person answers it. */
export function agentSteps(graph: Graph): AgentStep[] {
  const files = new Map(graph.nodes.filter((n) => n.labels.includes("File")).map((n) => [text(n.properties.path), text(n.properties.text)]));
  return graph.nodes
    .filter((n) => n.labels.includes("Step") && n.properties.kind === "Task_Agent")
    .sort((a, b) => Number(a.properties.line ?? 0) - Number(b.properties.line ?? 0))
    .map((n) => {
      const description = text(n.properties.description);
      const path = text(n.properties.prompt);
      // The server's graph carries a file's text; `aip compile --json`'s does not, and then the description stands in.
      const prompt = (path ? files.get(path) : "") || description;
      return { name: text(n.properties.name), description, prompt, person: forAPerson(description, prompt) };
    });
}
