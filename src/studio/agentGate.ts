// When "Complete with an agent" may run (S6a): the parts an agent must not invent are written, and the graph is
// valid. Step prose (descriptions, question instructions) may be empty; the agent fills it. Each reason names the
// step or field it is about, so the page can link to it.

import type { Draft } from "./draft";
import type { Issue } from "./lint";

export interface GateReason { message: string; stepId?: string; field?: string }

export function agentGate(draft: Draft, issues: Issue[]): GateReason[] {
  const out: GateReason[] = [];
  if (!draft.purpose.trim()) out.push({ message: "write the procedure's `purpose`", field: "purpose" });
  if (!draft.description.trim()) out.push({ message: "write the skill's `description`", field: "description" });
  if (!draft.triggerWhen.some((t) => t.trim())) out.push({ message: "write at least one `trigger_when` entry", field: "triggerWhen" });

  for (const s of draft.steps) {
    const label = s.name ? `step \`${s.name}\`` : `an unnamed ${s.kind} step`;
    if (s.kind === "router") continue;
    s.inputs.forEach((i, n) => { if (!i.name.trim()) out.push({ message: `${label}: input ${n + 1} has no name`, stepId: s.id, field: `inputs[${n}].name` }); });
    if (s.kind === "execution" || s.kind === "client_task") {
      const outputs = s.outputs ?? [];
      if (outputs.length === 0) out.push({ message: `${label} declares no outputs, so the agent would have to invent them`, stepId: s.id, field: "outputs" });
      outputs.forEach((o, n) => { if (!o.name.trim()) out.push({ message: `${label}: output ${n + 1} has no name`, stepId: s.id, field: `outputs[${n}].name` }); });
    }
    if (s.kind === "end" && s.inputs.length === 0) out.push({ message: `${label} declares no inputs, so the procedure returns nothing`, stepId: s.id, field: "inputs" });
    if (s.kind === "execution" && s.command !== undefined && s.command[0] !== "python") {
      out.push({ message: `${label} is launched with \`${s.command.join(" ")}\`; the agent writes Python scripts only, so set the command to python`, stepId: s.id, field: "command" });
    }
  }

  for (const i of issues) if (i.tier === "error") out.push({ message: `fix the error: ${i.message}`, stepId: i.stepId, field: i.field });
  return out;
}
