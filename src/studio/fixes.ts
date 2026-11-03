// One-click fixes for lint issues whose fix is unambiguous. Each returns a changed copy of the Draft. The ways to give
// an unproduced key a producer (declare it as a start input, or as an output of a step) need a choice, so the lint
// panel offers those separately (edit.ts: declareStartInput, declareOutput).

import type { Draft } from "./draft";
import { addStart, unreachedRunnable } from "./edit";
import type { Issue } from "./lint";

export interface Autofix { label: string; apply: (d: Draft) => Draft }

export function autofix(issue: Issue, draft: Draft): Autofix | undefined {
  if (issue.code === "missing_requires") {
    return {
      label: "add requires: python 3.10",
      apply: (d) => ({ ...structuredClone(d), requires: { interpreter: { name: "python", version: "3.10" }, packages: [], tools: [] } }),
    };
  }

  if (issue.code === "missing_start_step") {
    return { label: "add a start step", apply: (d) => addStart(d).draft };
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

  // A step with no next step: a runnable one hands off to the end, when there is exactly one; the start step hands
  // to the first runnable step nothing else reaches, when there is exactly one such step.
  if (issue.code === "schema_violation" && issue.field === "next" && step.next === undefined) {
    const target = step.kind === "start" ? onlyUnreached(draft) : onlyEnd(draft);
    if (!target) return undefined;
    return {
      label: `hand off to ${target.name || (step.kind === "start" ? "the first step" : "the end step")}`,
      apply: (d) => {
        const out = structuredClone(d);
        const s = out.steps.find((x) => x.id === step.id);
        if (s) s.next = target.id;
        return out;
      },
    };
  }
  return undefined;
}

function onlyEnd(d: Draft) {
  const ends = d.steps.filter((s) => s.kind === "end");
  return ends.length === 1 ? ends[0] : undefined;
}

/** The one runnable step no edge reaches, when there is exactly one: what a start step with no `inputs_to` meant. */
function onlyUnreached(d: Draft) {
  const candidates = unreachedRunnable(d);
  return candidates.length === 1 ? candidates[0] : undefined;
}
