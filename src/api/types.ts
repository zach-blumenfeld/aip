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

export interface StepDetail {
  name: string;
  kind: StepKind;
  order: number;
  description: string | null;
  branch_on?: string;   // router
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
  threshold: number | null;
}

export interface Resource {
  step: string;
  path: string;
  role: "script" | "template" | "asset" | "reference";
  description: string | null;
}

export interface FileEntry { path: string; size: number; sha256: string; mode: number }

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
  start: { step: string; kind: StepKind };
  end: { step: string; kind: StepKind };
  steps: Record<string, StepKind>;
  step_details: StepDetail[];
  edges: Edge[];
  branches: Branch[];
  inputs: StepInput[];
  outputs: StepOutput[];
  /** Null for a procedure with no execution steps. */
  requires: Requires | null;
  questions: Question[];
  resources: Resource[];
  files: FileEntry[];
}

export interface ApiErrorBody {
  error: { kind: string; message: string; location?: string; issues?: ValidationIssue[] };
}

// ---------------------------------------------------------------- run history (GET /runs/{id})

/** Who answered a decision (B4): the client's decision model, or the client by hand. */
export interface Attribution {
  resolver: "typesafe" | "manual";
  model: string | null;
  /** Per question, the model's confidence in the answer it chose. */
  confidence: Record<string, number> | null;
  reviewed: boolean;
  /** The model's answers before review, when reviewed. */
  proposed?: Record<string, boolean | string | number>;
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

/** One history entry: what a step received and produced. Routers record the branch they took. */
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

export interface ReviewItem {
  question: string;
  type: "noul" | "choice" | "score";
  reason: string;
  noul?: number;
  confidence?: number;
  probabilities?: Record<string, number>;
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
  /** Absent on an error. */
  severity?: "warning";
}

/** `POST /catalog`: the revision the files became (the existing one when nothing changed). */
export interface PublishResult { name: string; revision: string; id: string; warnings: ValidationIssue[] }
