// The prompt for "Complete with an agent" (S6a). The instructions are a shipped default the user may edit per run
// (the edit is saved with the draft); the frozen contract is generated from the Draft and always appended, so editing
// the instructions can never drop it. A string export rather than a `.md` import, like runtime-0.6a1.ts, so
// Playwright's Node loader can import it too.

import type { Draft, Step } from "./draft";
import { emptyProse } from "./agentCheck";
import type { Placeholder } from "./scaffold";
import { PLACEHOLDER_MARKER } from "./lint";

export const DEFAULT_AGENT_PROMPT = `You are finishing an AIP skill scaffold that a person designed in the AIP console's Studio. The zip you were given is the skill folder: SKILL.md (frontmatter, the AIP runtime block, and the procedure as a fenced YAML block), plus placeholder files under scripts/, assets/ and references/.

Your job:

1. Replace every file that holds the marker \`${PLACEHOLDER_MARKER}\` with a working script, template, reference or asset, and remove the marker. Execution scripts are Python. Write real, complete content: no TODOs, no stubs, no file that is empty or only comments.
2. Fill in the prose fields listed below as empty (step descriptions, question instructions and criteria text, empty \`trigger_when\` entries), in SKILL.md's YAML block. Fill only those.
3. Change nothing else. The graph, the step names and kinds, the edges and branches, every input and output name and type, the question names and types, the file paths, \`requires\`, and every field the person already wrote are frozen. If the design looks wrong, say so in your reply instead of changing it.
4. Run \`aip-spec validate <the skill folder>\` and fix what it reports until it prints VALID. Then run each script yourself with a sample stdin (the contract is below) and check it prints exactly its declared outputs.
5. Return the folder as a zip in the same layout: one top-level folder named after the skill, SKILL.md inside it.

The console checks your result itself: it validates it, compares SKILL.md to the design, runs every script with synthetic inputs, and rejects the whole result if any of it fails.`;

const io = (items: Step["inputs"]) => (items.length ? items.map((i) => `${i.name}: ${i.type}`).join(", ") : "(none)");

/** The frozen contract, from the Draft: every step with what may not change, the files to write, the empty prose. */
export function contract(draft: Draft, placeholders: Placeholder[]): string {
  const name = (id: string | undefined) => draft.steps.find((s) => s.id === id)?.name ?? "(unset)";
  const lines = [`## The design (frozen)`, "", `Skill \`${draft.name}\`. Steps, in order; the first is the start:`, ""];
  for (const s of draft.steps) {
    lines.push(`- \`${s.name}\` (${s.kind})`);
    if (s.kind === "router") {
      lines.push(`  - branch_on: \`${s.branchOn ?? ""}\``);
      for (const b of s.branches ?? []) lines.push(`  - \`${b.value}\` → \`${name(b.target)}\``);
      continue;
    }
    lines.push(`  - inputs: ${io(s.inputs)}`);
    if (s.kind === "execution" || s.kind === "client_task") lines.push(`  - outputs: ${io(s.outputs ?? [])}`);
    if (s.kind === "decision") for (const q of s.questions ?? []) lines.push(`  - question \`${q.name}\` (${q.type}${q.type === "choice" ? `: ${q.criteria.map((c) => c.label).join(", ")}` : q.type === "score" ? `: ${q.criteria.length} levels` : ""})`);
    if (s.script) lines.push(`  - script: \`${s.script}\`, launched with \`python ${s.script}\``);
    if (s.template) lines.push(`  - template: \`${s.template}\``);
    if (s.assets?.length) lines.push(`  - assets: ${s.assets.map((a) => `\`${a}\``).join(", ")}`);
    if (s.references?.length) lines.push(`  - references: ${s.references.map((r) => `\`${r.path}\``).join(", ")}`);
    if (s.kind !== "end") lines.push(`  - next: \`${name(s.next)}\``);
  }
  if (draft.requires) {
    const r = draft.requires;
    lines.push("", `requires: interpreter \`${r.interpreter.name}${r.interpreter.version ? ` >= ${r.interpreter.version}` : ""}\`; packages: ${r.packages.join(", ") || "(none)"}; tools: ${r.tools.join(", ") || "(none)"}. Use only the standard library and these packages.`);
  }

  lines.push("", "## Files to write", "");
  if (placeholders.length === 0) lines.push("None: no file holds the marker.");
  for (const p of placeholders) lines.push(`- \`${p.path}\` (${p.what} of step \`${name(p.stepId)}\`)`);

  const empty = emptyProse(draft);
  lines.push("", "## Empty prose fields to fill", "");
  if (empty.length === 0) lines.push("None.");
  for (const e of empty) lines.push(`- ${e}`);

  lines.push(
    "", "## The script contract", "",
    "Each execution script runs from the skill folder as `python <script>`, with `AIP_WORKDIR` set to the run's working directory. It reads one JSON object on stdin:",
    "", "    {\"state\": {<the step's inputs>}, \"assets\": {<file stem>: <file content as a string>}, \"expects\": <the next step's description>}", "",
    "and writes one JSON object to stdout holding exactly the step's declared outputs, each of its declared type (string, integer, float, boolean, object, list[*]). No other keys. A non-zero exit fails the step; diagnostics go to stderr.",
    "", "## Templates", "",
    "A client_task template is rendered with Python's `str.format` rules: `{key}` for each of the step's inputs, `{assets[stem]}` for each of its assets, `{meta.name}` for the skill name. Any other brace is doubled (`{{`, `}}`). The template tells the agent running the procedure what to do and asks for the step's outputs as one JSON object.",
    "", "The AIP runtime block at the top of SKILL.md is the full statement of how a run executes each step; `aip-spec schema` prints the JSON Schema of the YAML block.",
  );
  return lines.join("\n");
}

/** The prompt as it is copied or sent: the instructions (the draft's edit, else the default), then the contract. */
export function fullPrompt(draft: Draft, placeholders: Placeholder[]): string {
  return `${(draft.agentPrompt ?? DEFAULT_AGENT_PROMPT).trim()}\n\n${contract(draft, placeholders)}\n`;
}
