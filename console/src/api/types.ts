// The shapes the page reads: the aip server's replies (aip docs/server-design.md, section 2) and the
// run record (aip docs/cli-json.md, The run file), which is the same JSON whether the server hands it
// back or the CLI prints it from this machine's run file. Only what a view reads is typed. Types only:
// nothing here exists at run time.

import type { Graph } from "../graph/bundle.ts";

// ------------------------------------------------------------------ the catalog

export interface Revision {
  revision: string;
  bundle_id: string;
  published_at: string;
  retired: boolean;
}

/** One name of `GET /catalog`. */
export interface CatalogEntry {
  name: string;
  /** Of the revision the name resolves to. */
  description: string | null;
  pinned: string | null;
  /** The newest live revision; null once every revision is retired. */
  latest: string | null;
  /** What the bare name runs: the pinned revision, else the latest; null when nothing is live. */
  resolves: string | null;
  /** Newest first. */
  revisions: Revision[];
}

export interface SearchHit {
  name: string;
  revision: string;
  bundle_id: string;
  description: string;
  score: number;
}

/** One bundle of `GET /bundles`: a draft has no revision. */
export interface BundleRow {
  bundle_id: string;
  name: string;
  description: string | null;
  stored_at: string;
  draft: boolean;
  revision: string | null;
}

export type StepKind = "Start" | "Decide" | "Route" | "Aggregate" | "Execute" | "Task_Agent" | "End";

export interface StepSummary { name: string; kind: StepKind; description: string | null; loop: string | null; line: number }

export interface LoopSummary {
  name: string;
  kind: "For" | "Loop";
  mode: string | null;
  /** The loop's header after its name: `Until check_summary.all_hold, At_Most 3, Else_Fail`. */
  header: string;
  body: string[];
  loop: string | null;
  line: number;
}

/** What `aip info --json` prints and `GET /catalog/{ref}` and `GET /bundles/{id}` return. */
export interface Description {
  name: string;
  bundle_id: string;
  description: string;
  use_when: string[];
  do_not_use_when: string[];
  avoid: string[];
  /** What the machine that runs the scripts must have; null when the procedure names nothing. */
  requires: { interpreter: string | null; version: string | null } | null;
  steps: StepSummary[];
  loops: LoopSummary[];
  /** The `Start` step's keys and their types. */
  inputs: Record<string, string | null>;
  input_descriptions: Record<string, string>;
  /** The `End` step's keys and their types. */
  result: Record<string, string | null>;
  example_inputs: Record<string, unknown>;
  /** The Task_Agent steps written for a person, which `aip runah` stops at with no `--human` (plan R8). */
  human_steps?: string[];
  revision?: string | null;
  draft?: boolean;
  published_at?: string;
  retired?: boolean;
  stored_at?: string;
}

/** `GET /catalog/{ref}/graph`, `GET /bundles/{id}/graph`: the bundle's graph with the source and the files' text. */
export interface BundleGraph {
  name: string;
  revision: string | null;
  draft: boolean;
  bundle_id: string;
  graph: Graph;
}

/** A file of a bundle, read off its `File` node. */
export interface BundleFile { path: string; size: number; sha256: string; mode: number; text: string | null; base64: string | null }

export interface ApiErrorBody { error: { kind: string; message: string; location?: string } }

// ------------------------------------------------------------------ the run record

export interface Identity { agent: string | null; session: string | null; user: string | null }

/** One enclosing loop of an entry or a task, and which pass of it. */
export interface PassRef { loop: string; pass: number }

/** An answer (spec 2.4): a decision model's carries `confidence` and `probabilities`, a script's may, an
 *  agent's and an aggregation's are the value alone. */
export interface AnswerObject {
  value: boolean | string | number | null;
  confidence?: number;
  probabilities?: Record<string, number>;
  /** A score question's expected value. */
  score?: number;
  /** A true_or_false question's probability of true. */
  noul?: number;
}

/** A route's `Confidence_Below`, as it went. */
export interface Check { below: number; confidence: number | null; fired: boolean; reason?: string }

/** How one answer counted in an aggregation or an `Until`. */
export interface Resolution {
  /** In an aggregation, the answer judged (`policy_check.pii`); in an `Until`, `answer`. */
  source?: string;
  answer?: string;
  value: unknown;
  holds: boolean;
  /** The probability the answer put on the condition, which a `With Confidence_Above` bar reads. */
  probability: number | null;
  barred: boolean;
}

/** The test at a loop's head that let a pass run. */
export interface UntilTest { where: string; holds: boolean; resolution: Resolution | null }

/** How a loop ended: `until`, `items`, `times` or `cap`; `where` is `head` or the step that produced the answer. */
export interface LoopExit { reason: string; where?: string; resolution?: Resolution | null }

export interface Reference { path: string; description: string | null }

/** One entry of a run's history: what a step read and produced. A loop writes one too, when it exits. */
export interface HistoryEntry {
  step: string;
  kind: StepKind | "For" | "Loop";
  pass: number | null;
  passes: PassRef[];
  at: string;
  input: Record<string, unknown>;
  result: Record<string, unknown>;
  /** The step's own wall time. */
  seconds?: number;
  /** A `Decide`: the model and endpoint; a `Task_Agent`: the agent and session that resumed with the answer. */
  answered_by?: { model?: string | null; endpoint?: string | null; agent?: string | null; session?: string | null };
  /** A `Decide`: the model call alone, and whether it went out with other passes in one call. */
  model_seconds?: number;
  history_sent?: boolean;
  batched?: boolean;
  batch_size?: number;
  /** A `Route`: the dotted key it read, its check, the branch value taken (null when the check fired), where it went. */
  read?: string;
  check?: Check | null;
  value?: string | null;
  to?: string;
  /** An `Aggregate`: per aggregation, how each answer counted. */
  resolutions?: Record<string, Resolution[]>;
  /** An `Execute`. */
  script?: string;
  stdin?: unknown;
  /** A `Task_Agent` whose answering work is on record: `observed` when runah's model answered it (`answered_by` is
   *  `{agent: "runah", model}`; its tool calls one by one, its tokens, the model's time, how many of its answers were
   *  refused before one held), `reported` when the agent that answered said what it spent (`aip resume --work`: the
   *  tool calls as a count or a list, the tokens as a total or in full, the seconds it worked). */
  work?: "observed" | "reported";
  tool_calls?: number | { name: string; args?: string; seconds?: number; error?: string }[];
  tokens?: { prompt?: number; completion?: number; total: number };
  work_seconds?: number;
  refusals?: number;
  /** A `Task_Agent`: the task as handed over, and how long the agent took. */
  prompt?: string;
  references?: Reference[];
  waited_seconds?: number;
  /** A loop's own entry. */
  exit?: LoopExit;
  /** On the first entry of a `Loop Until` pass. */
  until?: UntilTest;
}

/** One task of a pause: a `For` pass waiting at the step, or the one task outside a loop. */
export interface Task {
  index: number;
  pass: number | null;
  passes: PassRef[];
  prompt: string;
  state: Record<string, unknown>;
  references: Reference[];
  /** The keys to answer with, and their types. */
  answer_with: Record<string, string>;
  /** For each `choice` or `score` key, the values it may take. */
  labels: Record<string, string[]>;
  /** In a capped `Loop`: whether this pass is the last the cap allows, and the cap. */
  last_pass?: boolean;
  pass_of?: number;
}

export interface Pause { kind: string; step: string; tasks: Task[]; since?: string }

/** A failed run's error (aip docs/cli-json.md, Error). */
export interface RunErrorBody {
  error: string;
  step: string | null;
  message: string;
  resumable?: boolean;
  loop?: string;
  cap?: number;
  count?: number;
  script?: string;
  exit_code?: number;
  stderr?: string;
  missing?: string[];
  invalid?: string[];
  missing_tasks?: number[];
  invalid_tasks?: number[];
  model?: string;
  endpoint?: string;
  cause?: string;
}

export type RunStatus = "paused" | "done" | "failed";

/** One row of `GET /runs` (and of `aip runs --json`, which has no `bundle_id` or `entries`). */
export interface RunSummary {
  run_id: string;
  name: string;
  revision: string | null;
  bundle_id?: string;
  status: RunStatus;
  draft: boolean;
  identity: Identity;
  started: string | null;
  finished: string | null;
  created: string | null;
  updated: string | null;
  entries?: number;
}

/** A run, whole: `GET /runs/{id}`, or `aip runs <id> --json` from this machine's run file. */
export interface RunRecord {
  run_id: string;
  bundle_id: string;
  name: string;
  revision: string | null;
  draft: boolean;
  status: RunStatus;
  /** `step:<name>` or `loop:<name>`: where a paused run waits or a failed one stopped; null once done. */
  position: string | null;
  started: string | null;
  finished: string | null;
  created?: string | null;
  updated?: string | null;
  identity: Identity;
  state: Record<string, unknown>;
  history: HistoryEntry[];
  pause: Pause | null;
  error: RunErrorBody | null;
  result: Record<string, unknown> | null;
  /** What `aip run` was given, and the run's working directory, on this machine's run file. */
  target?: string;
  workdir?: string | null;
  recorded?: boolean;
  /** A run started from a script of another run (the orchestrator, `docs/runah.md`): that run, the step and its pass. */
  parent?: { run_id: string; step: string | null; pass: number | null } | null;
  /** How many runs up the parent chain goes; with `parent` only. */
  depth?: number;
  /** runah's token budget for the run, its children's tokens included (`aip runah --budget-tokens`). */
  budget_tokens?: number;
  /** What runah's model spent: in this run, in the runs started from it, and the sum. */
  tokens?: { own: number; children: number; total: number };
  /** The runs this run's scripts started, with the step and pass that started each; absent when there are none. */
  children?: ChildRun[];
}

/** One run started from another run's script, as its parent's record lists it. */
export interface ChildRun {
  run_id: string;
  name: string | null;
  status: RunStatus;
  draft?: boolean;
  step: string | null;
  pass: number | null;
  tokens: number;
  started?: string | null;
}

// ------------------------------------------------------------------ audit

/** One query of `GET /audit`: a built-in, or one stored on the server. `needs` names parameters it cannot run without. */
export interface AuditQuery { query: string; description: string; builtin: boolean; needs: string[]; path: string }

/** A row of `GET /audit/{query}`: flat, with the columns the query defines. */
export type AuditRow = Record<string, unknown>;
