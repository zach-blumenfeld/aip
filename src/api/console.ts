// The console's own process (bin/aip-console.mjs): which server or folder it was started for, and
// interactive runs through the `aip` CLI it spawns. Everything else goes to the server directly
// (api/client.ts). The CLI's JSON lines are the contract of aip's docs/cli-json.md.

import { MissingValidator, type Runner } from "../studio/agentCheck";
import { store, type Upgrader } from "../studio/import";
import type { ZipFile } from "../zip";

/** `GET /console/config`. */
export interface ConsoleConfig {
  mode: "server" | "folder";
  server: string | null;
  folder: string | null;
  workdir: string;
  aip: { version: string; format: string };
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

// ------------------------------------------------------------------ the CLI's JSON (docs/cli-json.md)

/** `--progress`: one line per completed step. */
export interface StepEvent {
  event: "step";
  step: string;
  kind: "decision" | "router" | "execution" | "client_task";
  to?: string;
  resolver?: "typesafe" | "manual";
  seconds?: number;
}

export interface DecisionQuestion {
  type: "noul" | "choice" | "score";
  instructions?: string;
  /** noul: {true, false}; choice: label -> description; score: one description per level. */
  criteria?: Record<string, string | null> | (string | null)[];
}

interface Common { step: string; state: Record<string, unknown>; run_id: string | null; run_file?: string }

/** A decision pause: this client has no decision model and the step allows a manual answer (`fallback: true`).
 *  `confidence` names the questions whose `<question>_confidence` a model would have written; a manual answer
 *  writes none. */
export type Paused =
  | (Common & { paused: "decision"; questions: Record<string, DecisionQuestion>; confidence: string[]; fallback: boolean })
  | (Common & { paused: "client_task"; task: string; references: { uri: string; description: string }[]; answer_with: Record<string, string> });

export interface Done { done: true; run_id: string | null; state: Record<string, unknown>; run_file?: string }

export interface RunErrorObject {
  error: string;
  step: string | null;
  message: string;
  run_id: string | null;
  resumable: boolean;
  run_file?: string;
  script?: string;
  exit_code?: number;
  stderr?: string;
  seconds?: number;
  missing?: string[];
  invalid?: string[];
  status?: number;
  /** `no_decision_model`: the decision's `fallback`, always false here (a step that allows it pauses instead). */
  fallback?: boolean;
}

export type Outcome = Paused | Done | RunErrorObject;

/** How the `aip` process ended: its exit code, or the signal that stopped it (cancel). */
export interface Exit { code: number | null; signal: string | null; cancelled: boolean; stderr: string; error?: string }

export interface StreamHandlers {
  onSession?: (id: string) => void;
  onStep: (e: StepEvent) => void;
  onOutcome: (o: Outcome) => void;
  /** A line that is not one of the CLI's objects: shown, never parsed further. */
  onOther?: (line: string) => void;
}

/** Start `aip run` (`ref` and the start input) or `aip resume` (a run id and the answer, or none to retry),
 *  and feed what it prints to `handlers` as it arrives. Resolves with how the process ended. */
export async function runCli(
  call: { run: { ref: string; input: Record<string, unknown> } } | { resume: { run_id: string; input?: Record<string, unknown> } },
  handlers: StreamHandlers,
): Promise<Exit> {
  const [path, body] = "run" in call ? ["/console/run", call.run] : ["/console/resume", call.resume];
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
                                  body: JSON.stringify(body) });
  if (!res.ok || !res.body) {
    let message = `${res.status} ${res.statusText}`;
    try { message = ((await res.json()) as { error: { message: string } }).error.message; } catch { /* not JSON */ }
    throw new Error(message);
  }
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
      if (event === "session") handlers.onSession?.((JSON.parse(text) as { session: string }).session);
      else if (event === "exit") exit = JSON.parse(text) as Exit;
      else dispatch(text, handlers);
    }
  }
  return exit ?? { code: null, signal: null, cancelled: false, stderr: "", error: "the console's process closed the stream early" };
}

function dispatch(line: string, handlers: StreamHandlers) {
  let parsed: unknown;
  try { parsed = JSON.parse(line); } catch { handlers.onOther?.(line); return; }
  const o = parsed as Record<string, unknown>;
  if (o && o.event === "step") handlers.onStep(o as unknown as StepEvent);
  else if (o && ("paused" in o || "done" in o || "error" in o)) handlers.onOutcome(o as unknown as Outcome);
  else handlers.onOther?.(line);
}

/** Stop a running `aip` (and the scripts it started). */
export async function cancelCli(session: string): Promise<void> {
  await fetch("/console/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session }) });
}

/** `aip info <ref> --json` (the folder's, in folder mode) and its example start input. */
export interface SkillInfo {
  info: {
    meta: { name: string; description: string; version?: string };
    start: { step: string; kind: string; inputs: Record<string, string> };
    end: { step: string; kind: string; inputs: Record<string, string> };
    steps: Record<string, string>;
    decisions: Record<string, { fallback: boolean; confidence: string[] }>;
    routers: Record<string, { branch_on: string; confidence: { key: string; below: number; to: string } | null }>;
  };
  example_input: Record<string, unknown>;
}

export async function skillInfo(ref: string): Promise<SkillInfo> {
  const res = await fetch(`/console/skill?ref=${encodeURIComponent(ref)}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try { message = ((await res.json()) as { error: { message: string } }).error.message; } catch { /* not JSON */ }
    throw new Error(message);
  }
  return (await res.json()) as SkillInfo;
}

// ------------------------------------------------------------------ the Studio's agent checks (S6a)

/** `POST /console/validate` and `POST /console/probe`, as the checks in studio/agentCheck.ts run them. The files go
 *  as base64; a missing aip-spec is a MissingValidator, so the checks refuse rather than fail. */
export const consoleRunner: Runner = {
  async validate(name, files) {
    const res = await post("/console/validate", { name, files: files.map(store) });
    if (res.status === 503) throw new MissingValidator(await errorText(res));
    if (!res.ok) throw new Error(await errorText(res));
    return (await res.json()) as Awaited<ReturnType<Runner["validate"]>>;
  },
  async probe(name, files, script, stdin, timeout) {
    const res = await post("/console/probe", { name, files: files.map(store), script, stdin, timeout });
    if (!res.ok) return { code: null, error: await errorText(res) };
    return (await res.json()) as Awaited<ReturnType<Runner["probe"]>>;
  },
};

function post(path: string, body: unknown): Promise<Response> {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) });
}

async function errorText(res: Response): Promise<string> {
  try { return ((await res.json()) as { error: { message: string } }).error.message; } catch { return `${res.status} ${res.statusText}`; }
}

/** `POST /console/upgrade`: `aip upgrade` on the skill's files, as studio/import.ts's `upgradeDraft` runs it. */
export const consoleUpgrader: Upgrader = async (name, files) => {
  const res = await post("/console/upgrade", { name, files });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as Awaited<ReturnType<Upgrader>>;
};

/** The scaffold written to `<workdir>/studio/<name>/` for an agent to edit in place. */
export async function writeHandoff(name: string, files: ZipFile[]): Promise<{ dir: string; previous: string | null }> {
  const res = await post("/console/handoff", { name, files: files.map(store) });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as { dir: string; previous: string | null };
}

/** The handoff folder as it is now; `hash` changes whenever a file does. */
export async function readHandoff(name: string): Promise<{ dir: string; files: ZipFile[]; hash: string | null; missing?: boolean }> {
  const res = await post("/console/handoff/read", { name });
  if (!res.ok) throw new Error(await errorText(res));
  const body = (await res.json()) as { dir: string; files: { path: string; mode: number; b64: string }[]; hash: string | null; missing?: boolean };
  return { ...body, files: body.files.map((f) => ({ path: f.path, mode: f.mode, bytes: Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0)) })) };
}
