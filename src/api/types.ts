// Response shapes of the AIP server API (server-design.md §4.2). Only what the
// views read is typed; everything else stays `unknown` until a view needs it.

export interface Revision {
  revision: string;
  published_at: string;
  retired: boolean;
}

export interface CatalogEntry {
  name: string;
  description: string;
  pinned: string | null;
  /** The newest live revision; null once every revision is retired, when the name no longer resolves. */
  latest: string | null;
  revisions: Revision[];
}

export interface SearchHit {
  name: string;
  revision: string;
  description: string;
  score: number;
}

export type StepKind = "start" | "decision" | "router" | "execution" | "client_task" | "end";

/** What the validator made of what feeds a router's branch key, stored with the revision at publish: a start input
 *  or a script's output (`deterministic`), a decision model whose confidence the router checks (`measured`), or a
 *  probabilistic choice with no calibrated number behind it (`unmeasured`). */
export type SourceClass = "deterministic" | "measured" | "unmeasured";

/** A router's confidence check: below `below`, or with `key` absent or null, the run goes to `to`. */
export interface ConfidenceCheck { key: string; below: number; to: string }

export interface StepDetail {
  name: string;
  kind: StepKind;
  order: number;
  description: string | null;
  branch_on?: string;   // router
  /** router: the class of its source, null for a router the validator could not classify. */
  source_class?: SourceClass | null;
  /** router: its confidence check, null when it has none. */
  check?: ConfidenceCheck | null;
  /** decision: whether the client may answer by hand when it has no decision model. */
  fallback?: boolean;
  /** decision: the question names whose `<question>_confidence` the step emits. */
  confidence?: string[];
  script?: string;      // execution
  timeout?: number | null;
  /** How the script is launched, from its folder; null is `python <script>`. */
  command?: string[] | null;
  template?: string;    // client_task
  framing?: boolean;
}

export interface Edge { from: string; to: string }
export interface Branch { router: string; value: string; to: string }

export interface StepInput {
  step: string;
  order: number;
  name: string;
  type: string;
  description: string | null;
}

/** A key an execution or client_task step adds to the state; same shape as an input. */
export type StepOutput = StepInput;

/** What the machine that runs the scripts must have (the procedure's `requires`). */
export interface Requires {
  interpreter: { name: string; version: string | null };
  packages: string[];
  tools: string[];
}

export interface Question {
  step: string;
  order: number;
  name: string;
  type: string;
  instructions: string;
  criteria: string | null;   // JSON text
  /** Whether the step emits `<name>_confidence` into the state (the decision's `confidence` list names it). */
  confidence: boolean;
}

export interface Resource {
  step: string;
  path: string;
  role: "script" | "template" | "asset" | "reference";
  description: string | null;
}

export interface FileEntry { path: string; size: number; sha256: string; mode: number }

/** A warning or info the validator reported at publish, kept with the revision; `step` names the step it is on. */
export interface PublishIssue { code: string; severity: "warning" | "info"; step: string | null; location: string | null; message: string }

/** `GET /catalog/{ref}`: describe() plus the `aip info` fields and the projection. */
export interface ProcedureInfo {
  name: string;
  revision: string;
  id: string;
  description: string;
  aip_version: string | null;
  published_at: string;
  retired: boolean;
  purpose: string;
  trigger_when: string[];
  do_not_use_when: string[];
  anti_patterns: string[];
  example_input: Record<string, unknown>;
  start: { step: string; kind: StepKind; inputs: Record<string, string> };
  end: { step: string; kind: StepKind; inputs: Record<string, string> };
  steps: Record<string, StepKind>;
  /** Per decision: `fallback` and the questions whose confidence it emits. */
  decisions: Record<string, { fallback: boolean; confidence: string[] }>;
  /** Per router: its branch key and its check, with `to` the step's name. */
  routers: Record<string, { branch_on: string; confidence: ConfidenceCheck | null }>;
  step_details: StepDetail[];
  edges: Edge[];
  branches: Branch[];
  inputs: StepInput[];
  outputs: StepOutput[];
  /** Null for a procedure with no execution steps. */
  requires: Requires | null;
  questions: Question[];
  resources: Resource[];
  /** The validator's warnings and infos at publish (unmeasured routes, a key with several producers). */
  issues: PublishIssue[];
  files: FileEntry[];
}

export interface ApiErrorBody {
  error: { kind: string; message: string; location?: string; issues?: ValidationIssue[] };
}

// ---------------------------------------------------------------- run history (GET /runs/{id})

/** Who answered a decision: the client's decision model, or the client by hand (`fallback: true` on the step). */
export interface Attribution {
  resolver: "typesafe" | "manual";
  model: string | null;
  /** Per question, the probability the model put on the answer it gave: TypeSafe's confidence for a choice or
   *  score, `|2p - 1|` for a yes/no. Null for a manual answer: nobody invents a number. */
  confidence: Record<string, number> | null;
}

/** A decision's recorded result: one collapsed value per question. */
export interface DecisionResult {
  answers: Record<string, boolean | string | number>;
}

/** A client task's recorded result, written when the client answered: the task it was given and its answer. */
export interface ClientTaskResult {
  task: string;
  references: { uri: string; description: string }[];
  answer: Record<string, unknown>;
}

/** What a router's confidence check made of the state: whether it fired, and why (`low`: the key was under the
 *  bound; `absent`: a manual answer wrote no confidence; `null`: the key was null). */
export interface CheckOutcome { fired: boolean; reason: "low" | "absent" | "null" | null }

/** One history entry: what a step received and produced. The first is the start step's, its `input` the start
 *  input. Routers record the branch they took (`result.to`) and, with a check, `result.confidence`. */
export interface HistoryEntry {
  step: string;
  kind: StepKind | "error";
  input: Record<string, unknown>;
  result: Record<string, unknown>;
  /** Decisions: who answered. */
  attribution?: Attribution;
  /** Execution steps: wall time on the client that ran the script. */
  seconds?: number;
  /** Execution steps: the client machine that ran the script (on an error entry, it is in `result`). */
  host?: string;
  /** Errors: the kind of the step that failed. */
  step_kind?: StepKind;
}

export type RunStatus = "running" | "paused" | "done" | "failed";

export interface RunSummary {
  run_id: string;
  name: string;
  revision: string;
  status: RunStatus;
  started_at: string;
  updated_at: string;
  steps: number;
}

/** Where a run waits, in the client's pause shape (aip docs/cli-json.md) with `kind` for `paused`. */
export type RunPause =
  | { kind: "client_task"; step: string; task: string; state: Record<string, unknown>; references: { uri: string; description: string }[]; answer_with: Record<string, string> }
  | { kind: "decision"; step: string; state: Record<string, unknown>; questions: Record<string, unknown> }
  | { kind: "execute"; step: string; script: string }
  | { kind: "error"; step: string; error: string }
  | { kind: "done"; state: Record<string, unknown>; step?: undefined };

/** `GET /runs/{id}`: the summary fields plus the full history and the pause block. */
export interface RunDetail {
  run_id: string;
  name: string;
  revision: string;
  status: RunStatus;
  started_at: string;
  updated_at: string;
  pause: RunPause | null;
  history: HistoryEntry[];
}

// ------------------------------------------------------------------- governance (§7, §10.5)

/** One entry of `GET /governance`: a named corpus query and where to ask it. */
/** One query of `GET /governance`: a built-in, or one stored on the server (`builtin: false`), which runs read-only. */
export interface GovernanceQuery { query: string; description: string; path: string; builtin: boolean }

/** A row of `GET /governance/{query}`: flat, with the columns the query defines. */
export type GovernanceRow = Record<string, unknown>;

// ------------------------------------------------------------------- publish (POST /catalog)

/** One issue of the server's validation, in a 422 `invalid_skill` envelope (`issues`), or a warning of a
 *  publish that went through. Paths are relative to the upload. */
export interface ValidationIssue {
  path: string;
  kind: string;
  message: string;
  location?: string;
  /** Absent on an error. An info never fails a publish. */
  severity?: "warning" | "info";
}

/** `POST /catalog`: the revision the files became (the existing one when nothing changed). */
export interface PublishResult { name: string; revision: string; id: string; warnings: ValidationIssue[] }
