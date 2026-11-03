// The Studio's working copy of a procedure. It mirrors aip-spec's `ProcedureSpec` but may be incomplete: fields
// are empty or missing, step names may be empty or duplicate, edges may be unset. Edges reference step *ids*, so a
// rename never breaks one; names appear only on export (serialize.ts) and in lint messages.

export const FORMAT_VERSION = "0.8";

export const DATA_TYPES = ["string", "integer", "float", "boolean", "object", "list[*]"] as const;
export type DataType = (typeof DATA_TYPES)[number];

export type StepKind = "start" | "decision" | "execution" | "client_task" | "router" | "end";
export const RUNNABLE_KINDS: readonly StepKind[] = ["decision", "execution", "client_task"];

/** The type a collapsed answer lands as in the state, per question type (aip-spec's QUESTION_TYPES). */
export const QUESTION_TYPES = { noul: "boolean", choice: "string", score: "integer" } as const;
/** The type of a confidence key (aip-spec's CONFIDENCE_TYPE), and what a router may branch on (BRANCHABLE_TYPES). */
export const CONFIDENCE_TYPE = "float";
export const BRANCHABLE_TYPES: readonly string[] = ["boolean", "string", "integer"];

/** The state key a decision's `confidence` list emits for a question. Fixed, not configurable. */
export const confidenceKey = (question: string) => `${question}_confidence`;

/** `type` is a plain string, not a DataType: an imported skill may carry anything and the linter says so. */
export interface IOItem { name: string; type: string; description?: string }

export interface Reference { path: string; description: string }

interface QuestionBase { name: string; instructions: string }
export interface NoulQuestion extends QuestionBase { type: "noul"; criteria?: { true?: string; false?: string } }
/** An ordered list rather than a map, so a label can be edited, and duplicated, mid-edit. */
export interface ChoiceQuestion extends QuestionBase { type: "choice"; criteria: { label: string; description: string | null }[] }
export interface ScoreQuestion extends QuestionBase { type: "score"; criteria: string[] }
export type Question = NoulQuestion | ChoiceQuestion | ScoreQuestion;

export interface Branch { value: string; target?: string }

/** A router's confidence check (`confidence` in the YAML): below the bound, or with the key absent or null, the run
 *  goes to `to`, the id of a step. `below` is unset while it is being typed; the linter says so. */
export interface ConfidenceCheck { key: string; below?: number; to?: string }

/** One step of any kind. The fields a kind does not use are left unset. */
export interface Step {
  id: string;
  kind: StepKind;
  name: string;
  description: string;
  /** start: the procedure's inputs, what the client supplies. Runnable steps and the end: the keys they read. */
  inputs: IOItem[];
  /** execution, client_task */
  outputs?: IOItem[];
  /** start, decision, execution, client_task: the id of the step that receives the output. */
  next?: string;
  /** decision */
  questions?: Question[];
  /** decision: the question names whose `<question>_confidence` the step emits. */
  confidence?: string[];
  /** decision: whether the client may answer by hand when it has no decision model; off by default. */
  fallback?: boolean;
  history?: boolean;
  /** execution */
  script?: string;
  command?: string[];
  timeout?: number;
  /** execution, client_task */
  assets?: string[];
  /** client_task */
  template?: string;
  references?: Reference[];
  framing?: boolean;
  /** router */
  branchOn?: string;
  check?: ConfidenceCheck;
  branches?: Branch[];
}

export interface Requires {
  interpreter: { name: string; version?: string };
  packages: string[];
  tools: string[];
}

export interface Draft {
  // frontmatter
  name: string;
  description: string;
  compatibility?: string;
  license?: string;
  allowedTools?: string;
  aipVersion: string;
  // the procedure block
  purpose: string;
  triggerWhen: string[];
  doNotUseWhen: string[];
  antiPatterns: string[];
  requires?: Requires;
  /** Exactly one step has kind `start` (by convention the first; the export writes it first) and one has kind `end`. */
  steps: Step[];
  // carried from an import (S4)
  /** `metadata` keys besides `aip-version`, kept as they were. */
  metadata?: Record<string, string>;
  /** The SKILL.md the draft was imported from: the export writes its edits into this text, so formatting the
   *  Studio did not touch stays as it was (patch.ts). */
  origin?: string;
  /** The imported skill's other files, emitted as they are. */
  files?: StoredFile[];
  /** The agent prompt as edited for this draft (S6a); unset is the shipped default. */
  agentPrompt?: string;
  /** The folder handed to an agent (S6b): where the scaffold was written, and the hash of it as written, so the
   *  Studio checks only once the agent has changed something. */
  handoff?: { name: string; dir: string; baseline: string | null };
}

/** A file kept with a draft, base64 so the draft stays JSON for localStorage. */
export interface StoredFile { path: string; mode: number; b64: string }

/** An id that names no step: what an imported edge to an undeclared step name becomes, so it lints as such. */
export const UNRESOLVED = "unresolved:";

/** The `start` step of a draft: the first step of that kind, as aip-spec takes it (any position, exactly one). */
export const startOf = (steps: Step[]): Step | undefined => steps.find((s) => s.kind === "start");

export function emptyDraft(): Draft {
  return {
    name: "", description: "", aipVersion: FORMAT_VERSION, purpose: "",
    triggerWhen: [""], doNotUseWhen: [], antiPatterns: [], steps: [],
  };
}

let counter = 0;
/** A fresh step id, unique within the page session; ids restored from storage are never regenerated. */
export function newStepId(taken: Iterable<string> = []): string {
  const used = new Set(taken);
  let id: string;
  do { id = `s${++counter}`; } while (used.has(id));
  return id;
}
