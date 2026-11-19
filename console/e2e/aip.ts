import { execFileSync } from "node:child_process";
import path from "node:path";

// Everything the e2e run uses lives under .aip-e2e/, written fresh by e2e/prepare.mjs.
export const E2E = path.resolve(import.meta.dirname, "..", ".aip-e2e");

export const AIP_PORT = Number(process.env.AIP_E2E_PORT ?? 8765);
export const MODEL_PORT = Number(process.env.MODEL_E2E_PORT ?? 8766);
export const AGENT_MODEL_PORT = Number(process.env.AGENT_MODEL_E2E_PORT ?? 8767);
export const CONSOLE_PORT = Number(process.env.CONSOLE_E2E_PORT ?? 5174);
export const FOLDER_PORT = Number(process.env.FOLDER_E2E_PORT ?? 5175);
export const SERVER = `http://localhost:${AIP_PORT}`;
export const MODEL = `http://127.0.0.1:${MODEL_PORT}`;
/** The stand-in chat model `aip agent --answer` asks (e2e/agent.mjs) when the console drives a run, which answers
 *  build_procedure's and edit_procedure's tasks from a script: configured as `stand-in-1`, it reports itself as `stand-in-1-snapshot` in each reply. */
export const AGENT_MODEL = `http://127.0.0.1:${AGENT_MODEL_PORT}/v1`;
export const AGENT_MODEL_NAME = "stand-in-1";
export const AGENT_MODEL_REPORTED = "stand-in-1-snapshot";

/** The aip repo this console is run against: the repository it lives in. */
export const AIP_REPO = path.resolve(process.env.AIP_REPO ?? path.join(import.meta.dirname, "..", ".."));

/** The `aip` the consoles find first on their PATH: the repo's CLI behind `uv run`. */
export const BIN = path.join(E2E, "bin");

/** The published procedures, by the name each `Procedure` line gives. */
export const AGENT = "billing_support_agent";     // `triage` is a Task_Agent: no decision model needed
export const BILLING = "billing_support";         // `triage` is a Decide: the e2e model answers
export const FIXED = "fixed_policy";              // a Loop Until with a cap
export const DYNAMIC = "dynamic_policy";          // a For inside the Loop, its passes one batched model call
export const TRIAGE = "ticket_triage";            // a For whose passes pause together

/** The two revisions of billing_support_agent (v2 changes one policy line), the folder the folder console runs
 *  (v1), and a reworded copy that is never published: its runs are a draft's. */
export const FIRST_REVISION_DIR = path.join(E2E, "v1", "billing-support-agent");
export const SECOND_REVISION_DIR = path.join(E2E, "v2", "billing-support-agent");
export const DRAFT_DIR = path.join(E2E, "draft", "billing-support-agent");
export const CHANGED_FILE = "assets/policy.md";
export const OLD_LINE = "- Refunds for other reasons are honored within 30 days of purchase.";
export const NEW_LINE = "- Refunds for other reasons are honored within 45 days of purchase.";

export const folderOf = (example: string) => path.join(E2E, example);

/** The server's store, and the consoles' working directories. */
export const STORE = path.join(E2E, "store", "store.rl");
export const WORKDIR = path.join(E2E, "work");
export const FOLDER_WORKDIR = path.join(E2E, "work-folder");

/** The CLI's environment in the e2e run: its own run files and bundle cache, no client config, the e2e decision
 *  model (e2e/model.mjs), which answers from marks in the text it is given, and the stand-in chat model for
 *  `aip config agent` (e2e/agent.mjs) in place of any this machine's shell names. The server is set per call. */
export const CLI_ENV = {
  PATH: `${BIN}:${process.env.PATH}`,
  AIP_HOME: path.join(E2E, "home"),
  AIP_CONFIG: path.join(E2E, "no-config.json"),
  AIP_DECISION_MODEL: MODEL,
  AIP_DECISION_MODEL_KEY: "e2e",
  AIP_AGENT_MODEL_URI: AGENT_MODEL,
  AIP_AGENT_MODEL_KEY: "e2e",
  AIP_AGENT_MODEL_NAME: AGENT_MODEL_NAME,
};

/** `aip <args>` against the e2e server, as the specs' own client (publishing, making runs for history), from the
 *  console's working directory so the scripts' files stay out of the repo. `agent` and `session` are who it says it is. */
export function aip(args: string[], input?: unknown, who: { agent?: string; session?: string } = {}): string {
  try {
    return execFileSync(path.join(BIN, "aip"), args, {
      cwd: WORKDIR,
      env: { ...process.env, ...CLI_ENV, AIP_SERVER: SERVER, AIP_AGENT: who.agent ?? "e2e", ...(who.session ? { AIP_SESSION: who.session } : {}) },
      input: input === undefined ? undefined : JSON.stringify(input),
      encoding: "utf8",
    });
  } catch (e) {
    const out = e as { stdout?: string; status?: number };
    if (out.stdout && out.status === 1) return out.stdout;   // an error object: the caller reads it
    throw e;
  }
}

type Json = Record<string, unknown>;

/** `aip run <target>` with the inputs on stdin: the one JSON object it prints. */
export function run(target: string, inputs: Json, who: { agent?: string; session?: string } = {}): Json {
  return JSON.parse(aip(["run", target, "--inputs", "-", "--workdir", WORKDIR], inputs, who)) as Json;
}

/** `aip resume <run id>` with the answers on stdin (none: retry the failed step): the one JSON object it prints. `work`
 *  is what the answering agent reports it spent (`--work`). */
export function resume(runId: string, answers?: unknown, who: { agent?: string; session?: string } = {}, work?: Json): Json {
  const args = answers === undefined ? ["resume", runId] : ["resume", runId, "--answers", "-"];
  if (work !== undefined) args.push("--work", JSON.stringify(work));
  return JSON.parse(aip(args, answers, who)) as Json;
}
