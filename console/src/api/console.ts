// The console's own process (bin/aip-console.mjs): which server or folder it was started for, and
// everything that goes through the `aip` CLI on this machine: runs and resumes (their JSON lines relayed
// as they are printed), a folder's description and graph, this machine's run files. The rest goes to
// the server directly (api/client.ts). The CLI's JSON is the contract of aip's docs/cli-json.md.

import type { Graph } from "../graph/bundle.ts";
import type { Description, PassRef, RunErrorBody, RunRecord, RunSummary, Task } from "./types";

/** `GET /console/config`. */
export interface ConsoleConfig {
  mode: "server" | "folder";
  server: string | null;
  /** The server is the one `aip config server local` starts on demand: it stops when idle and the launcher wakes it. */
  local: boolean;
  folder: string | null;
  workdir: string;
  aip: { version: string; language: string };
  minimum: string;
}

let loaded: ConsoleConfig | null = null;

/** Fetched once before the app renders (main.tsx); every view reads it synchronously after. */
export async function loadConsoleConfig(): Promise<ConsoleConfig> {
  const res = await fetch("/console/config", { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`the console's process answered ${res.status} for /console/config; start the page with \`aip-console\``);
  loaded = (await res.json()) as ConsoleConfig;
  return loaded;
}

export function consoleConfig(): ConsoleConfig {
  if (!loaded) throw new Error("the console config is not loaded yet");
  return loaded;
}

export const isFolderMode = () => consoleConfig().mode === "folder";

async function errorText(res: Response): Promise<string> {
  try { return ((await res.json()) as { error: { message: string } }).error.message; } catch { return `${res.status} ${res.statusText}`; }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as T;
}

function post(path: string, body: unknown): Promise<Response> {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) });
}

/** Ask the launcher to start the local server (any `aip` command does); false when there is none to start. */
export async function wakeServer(): Promise<boolean> {
  if (!loaded || !loaded.local) return false;
  try { return (await post("/console/wake", {})).ok; } catch { return false; }
}

/** This browser tab's session id, the `session` of the runs it starts and answers: history filters by it. */
export function sessionId(): string {
  const key = "aip.session";
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = `console-${Math.random().toString(16).slice(2, 10)}`;
    sessionStorage.setItem(key, id);
  }
  return id;
}

// ------------------------------------------------------------------ the CLI's JSON (docs/cli-json.md)

/** `--progress`: one line per history entry as the run writes it. */
export interface StepEvent {
  event: "step";
  step: string;
  kind: string;
  pass: number | null;
  passes: PassRef[];
  seconds?: number;
  /** A `Route`: where it went, and whether its `Confidence_Below` fired. */
  to?: string;
  fired?: boolean;
  /** A `Decide`: each question's value and confidence. */
  answers?: Record<string, { value: unknown; confidence?: number }>;
  answered_by?: { model?: string | null; endpoint?: string | null; agent?: string | null; session?: string | null };
  /** An `Aggregate`: each aggregation's value. */
  result?: Record<string, unknown>;
  /** A loop's exit: why, where, after how many passes. */
  exit?: string;
  where?: string;
  iterations?: number;
}

/** `aip agent --answer --progress` (plan C6): the model answered the pause at `step` (`answer`: the tokens and seconds
 *  of the call), the run refused that answer and it went back to the model (`refused`), or no answer held and the run
 *  is left paused (`gave_up`). */
export interface ModelEvent {
  event: "answer" | "refused" | "gave_up";
  step: string;
  run_id: string;
  tokens?: number;
  seconds?: number;
  reason?: string;
}

interface Stop { run_id: string | null; run_file?: string; recorded?: boolean }

/** Why a driven run stopped for the page (the launcher says, plan C6): a person's step (`person`), or a pause the model
 *  did not answer (it gave up, or has no key), with why. */
export interface Answerer { person: boolean; reason: string }

/** The Studio's person's step: build_procedure's `ask_user`; the model answers the rest (the launcher's `STUDIO_PERSON`). */
export const STUDIO_PERSON = ["ask_user"];

/** A pause: every `For` pass waiting at the step is one task, answered together. */
export interface Paused extends Stop { paused: string; step: string; tasks: Task[]; hint: string; answerer?: Answerer }

export interface Done extends Stop { done: true; result: Record<string, unknown> }

export interface Failed extends Stop, RunErrorBody { resumable: boolean; pass?: number | null; passes?: PassRef[]; kind?: string }

export type Outcome = Paused | Done | Failed;

/** How the `aip` process ended: its exit code, or the signal that stopped it (cancel). */
export interface Exit { code: number | null; signal: string | null; cancelled: boolean; stderr: string; error?: string }

export interface StreamHandlers {
  /** The launcher's id for the process, to cancel it by. */
  onProcess?: (id: string) => void;
  onStep: (e: StepEvent) => void;
  /** The model's calls, when it answers a driven run's pauses. */
  onModel?: (e: ModelEvent) => void;
  onOutcome: (o: Outcome) => void;
  /** A line that is not one of the CLI's objects: shown, never parsed further. */
  onOther?: (line: string) => void;
}

export type CliCall =
  | { run: { ref: string; inputs: Record<string, unknown> } }
  /** `aip run`, driven (plan C6): the model answers every pause but those at the `person` steps, where the run stops. */
  | { agent: { ref: string; inputs: Record<string, unknown>; person: string[]; studio?: boolean } }
  /** `aip resume`; with `person`, a driven run goes on driven; `studio` records it as the studio's. */
  | { resume: { run_id: string; answers?: unknown; studio?: boolean; workspace?: string; person?: string[] } }
  | { build: { workspace: string; brief: string; title?: string; source?: string; files?: Record<string, string> } }
  | { edit: { workspace: string; instruction: string; source?: string; files?: Record<string, string> } };

function callOf(call: CliCall): [string, object] {
  if ("run" in call) return ["/console/run", call.run];
  if ("agent" in call) return ["/console/agent", call.agent];
  if ("resume" in call) return ["/console/resume", call.resume];
  if ("build" in call) return ["/console/studio/build", call.build];
  return ["/console/studio/edit", call.edit];
}

/** Start `aip run` (a reference and the inputs) or `aip resume` (a run id and the answers, or none to retry), driven
 *  or not, or one of the Studio's runs (build_procedure, edit_procedure, driven), and feed what it prints to
 *  `handlers` as it arrives. Resolves with how the process ended. */
export async function runCli(call: CliCall, handlers: StreamHandlers): Promise<Exit> {
  const [path, body] = callOf(call);
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
                                  body: JSON.stringify({ ...body, session: sessionId() }) });
  if (!res.ok || !res.body) throw new Error(await errorText(res));
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let exit: Exit | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data.push(line.slice(6));
      }
      const text = data.join("\n");
      if (event === "process") handlers.onProcess?.((JSON.parse(text) as { process: string }).process);
      else if (event === "exit") exit = JSON.parse(text) as Exit;
      else dispatch(text, handlers);
    }
  }
  return exit ?? { code: null, signal: null, cancelled: false, stderr: "", error: "the console's process closed the stream early" };
}

function dispatch(line: string, handlers: StreamHandlers) {
  let parsed: unknown;
  try { parsed = JSON.parse(line); } catch { handlers.onOther?.(line); return; }
  const o = parsed as Record<string, unknown> | null;
  if (o && o.event === "step") handlers.onStep(o as unknown as StepEvent);
  else if (o && (o.event === "answer" || o.event === "refused" || o.event === "gave_up")) {
    if (handlers.onModel) handlers.onModel(o as unknown as ModelEvent);
    else handlers.onOther?.(line);
  }
  else if (o && ("paused" in o || "done" in o || "error" in o)) handlers.onOutcome(o as unknown as Outcome);
  else handlers.onOther?.(line);
}

/** Stop a running `aip` (and the scripts it started). */
export async function cancelCli(process: string): Promise<void> {
  await post("/console/cancel", { process });
}

/** `aip info <ref> --json`: the description of a published name, or of the folder in folder mode. */
export function describeProcedure(ref?: string): Promise<Description> {
  return getJson<Description>(`/console/procedure${ref ? `?ref=${encodeURIComponent(ref)}` : ""}`);
}

/** One diagnostic of `aip compile --json`. */
export interface Diagnostic { code: string; severity: string; message: string; line: number | null; column: number | null; step: string | null }
/** `GET /console/graph`, folder mode: `aip compile --check --json` on the folder, and the text of its procedure.aip. */
export interface FolderGraph { ok: boolean; bundle_id: string | null; diagnostics: Diagnostic[]; graph: Graph | null; source: string }

export function folderGraph(): Promise<FolderGraph> {
  return getJson<FolderGraph>("/console/graph");
}

// ------------------------------------------------------------------ the Studio (plans C2, C4)

/** What the Studio's check makes of a source: the formatted text, and the compiler's report on it (the graph as far
 *  as it goes when it has errors, `partial`). */
export interface StudioCheck { source: string; formatted: boolean; ok: boolean; bundle_id: string | null; diagnostics: Diagnostic[]; graph: Graph | null; partial: boolean }

/** What saving did: `aip publish [--draft] --json`, and the source as saved. */
export interface StudioSaved {
  name: string; revision: string | null; bundle_id: string; existed: boolean; draft: boolean; source: string;
  /** The console kept the bundle as saved, so the Run button can run it (`bundle:<id>`). */
  runnable?: boolean;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await post(path, body);
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as T;
}

/** A folder on this machine holding the procedure's files (none for a new one), named `name`, for the checks, the
 *  chat's runs and the save. */
export function studioOpen(files: { path: string; text: string | null; base64: string | null; mode: number }[], name?: string): Promise<{ workspace: string }> {
  return postJson("/console/studio/open", { files, name });
}

/** The folder as it is on disk, after a run changed it or an undo put it back: the check of its procedure.aip, its
 *  name, its text files, and how many runs can be undone. */
export interface StudioRead extends StudioCheck { name: string; files: Record<string, string>; undo: number }

export function studioRead(workspace: string): Promise<StudioRead> {
  return postJson("/console/studio/read", { workspace });
}

/** Put the folder back as it was before the last run. */
export function studioUndo(workspace: string): Promise<StudioRead> {
  return postJson("/console/studio/undo", { workspace });
}

/** Documents dropped on the chat, saved under the draft's assets/docs/: build_procedure and edit_procedure read them. */
export function studioDocuments(workspace: string, documents: { name: string; base64: string }[]): Promise<{ documents: string[] }> {
  return postJson("/console/studio/documents", { workspace, documents });
}

/** One model `aip config` names: where it is, which model, whether a key is set (never the key), and where that came
 *  from (the config file, or the environment, which wins; null when nothing is set and the defaults show). */
export interface ModelSetting { endpoint: string; model: string | null; key: boolean; source: string | null }
/** `agent` is the chat model that answers a driven run's pauses (`aip config agent`, the one `aip agent` asks); `decision`
 *  the decision model. */
export interface ModelSettings { agent: ModelSetting | null; decision: ModelSetting | null }
export interface ModelSettingsChange {
  agent_model_uri?: string; agent_model_name?: string; agent_model_key?: string; decision_model?: string; decision_model_key?: string;
}

export function modelSettings(): Promise<ModelSettings> {
  return getJson<ModelSettings>("/console/settings");
}

/** Written through `aip config`; an empty string forgets a setting. */
export function saveModelSettings(change: ModelSettingsChange): Promise<ModelSettings> {
  return postJson("/console/settings", change);
}

export function studioCheck(workspace: string, source: string, files: Record<string, string>): Promise<StudioCheck> {
  return postJson("/console/studio/check", { workspace, source, files });
}

/** Save as a draft, or with `publish` as the next revision (the draft of the same bundle gets it). */
export function studioSave(workspace: string, source: string, files: Record<string, string>, publish: boolean): Promise<StudioSaved> {
  return postJson("/console/studio/save", { workspace, source, files, publish });
}

/** A run from this machine's run file (`aip runs <id> --json`): what a run that was not recorded leaves. */
export function localRun(runId: string): Promise<RunRecord> {
  return getJson<RunRecord>(`/console/record?run_id=${encodeURIComponent(runId)}`);
}

/** This machine's run files (`aip runs --json`); in folder mode, the folder's runs. */
export function localRuns(): Promise<RunSummary[]> {
  return getJson<RunSummary[]>("/console/runs");
}
