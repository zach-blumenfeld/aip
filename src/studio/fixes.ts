// One-click fixes for lint issues whose fix is unambiguous. Each returns a changed copy of the Draft. The ways to give
// an unproduced key a producer (declare it as a start input, or as an output of a step) need a choice, so the lint
// panel offers those separately (edit.ts: declareStartInput, declareOutput).

import type { Draft } from "./draft";
import type { Issue } from "./lint";

export interface Autofix { label: string; apply: (d: Draft) => Draft }

export function autofix(issue: Issue, draft: Draft): Autofix | undefined {
  if (issue.code === "missing_requires") {
    return {
      label: "add requires: python 3.10",
      apply: (d) => ({ ...structuredClone(d), requires: { interpreter: { name: "python", version: "3.10" }, packages: [], tools: [] } }),
    };
  }

  const step = draft.steps.find((s) => s.id === issue.stepId);
  if (!step) return undefined;

  if (issue.code === "undeclared_launcher" && step.command?.[0] && draft.requires) {
    const tool = step.command[0];
    return {
      label: `add ${tool} to requires.tools`,
      apply: (d) => {
        const out = structuredClone(d);
        if (out.requires && !out.requires.tools.includes(tool)) out.requires.tools.push(tool);
        return out;
      },
    };
  }

  // A runnable step with no next step: hand off to the end, when there is exactly one.
  if (issue.code === "schema_violation" && issue.field === "next" && step.next === undefined) {
    const ends = draft.steps.filter((s) => s.kind === "end");
    if (ends.length !== 1) return undefined;
    const end = ends[0];
    return {
      label: `hand off to ${end.name || "the end step"}`,
      apply: (d) => {
        const out = structuredClone(d);
        const s = out.steps.find((x) => x.id === step.id);
        if (s) s.next = end.id;
        return out;
      },
    };
  }
  return undefined;
}
