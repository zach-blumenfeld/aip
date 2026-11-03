import { execFileSync } from "node:child_process";
import path from "node:path";

// Everything the e2e run uses lives under .aip-e2e/, written fresh by e2e/prepare.mjs.
export const E2E = path.resolve(import.meta.dirname, "..", ".aip-e2e");

export const AIP_PORT = Number(process.env.AIP_E2E_PORT ?? 8765);
export const CONSOLE_PORT = Number(process.env.CONSOLE_E2E_PORT ?? 5174);
export const FOLDER_PORT = Number(process.env.FOLDER_E2E_PORT ?? 5175);
export const SERVER = `http://localhost:${AIP_PORT}`;

/** The aip repo this console is developed against (a clone with the dev group). */
export const AIP_REPO = path.resolve(process.env.AIP_REPO ?? path.join(import.meta.dirname, "..", "..", "aip"));

/** The `aip` the consoles find first on their PATH: the aip repo's CLI behind `uv run`. */
export const BIN = path.join(E2E, "bin");

/** aip-spec's example as shipped (`aip-spec example billing-support`): what the lint specs read, since its router
 *  checks `tone_confidence` and its decision keeps `fallback: true`, the one warning the example carries. */
export const EXAMPLE_DIR = path.join(E2E, "example", "billing-support");

/** The two revisions of billing-support the consoles drive (v2 changes one policy line), and the folder the folder
 *  console runs. Their router has no confidence check: the e2e CLI has no decision model, every decision is answered
 *  by hand and so records no confidence, and a check would send every run to `escalate`; without it, the tone
 *  answered in the page picks the branch, so both branches are reachable from the console. */
export const FIRST_REVISION_DIR = path.join(E2E, "v1", "billing-support");
export const SECOND_REVISION_DIR = path.join(E2E, "v2", "billing-support");

/** The example as shipped, under another name: its router checks `tone_confidence` (below 0.6, or absent, to
 *  `escalate`), so the specs that need a check to fire or hold drive this one. */
export const CHECKED = "billing-checked";
export const CHECKED_REVISION_DIR = path.join(E2E, "checked", CHECKED);
export const CHANGED_FILE = "assets/policy.md";
export const OLD_LINE = "- Refunds for other reasons are honored within 30 days of purchase.";
export const NEW_LINE = "- Refunds for other reasons are honored within 45 days of purchase.";

/** The filesystem root the e2e server runs over, and the consoles' working directories. */
export const ROOT = path.join(E2E, "root");
export const WORKDIR = path.join(E2E, "work");
export const FOLDER_WORKDIR = path.join(E2E, "work-folder");

/** The CLI's environment in the e2e run: its own run files, no client config, no decision model, so every
 *  decision pauses for the console to answer. The server is set per call. */
export const CLI_ENV = {
  PATH: `${BIN}:${process.env.PATH}`,
  AIP_HOME: path.join(E2E, "home"),
  AIP_CONFIG: path.join(E2E, "no-config.json"),
  TYPESAFE_API_KEY: "",
};

/** `aip <args>` against the e2e server, as the specs' own client (publishing, driving runs for history), from
 *  the console's working directory so the scripts' files stay out of the repo. */
export function aip(args: string[], input?: unknown): string {
  try {
    return execFileSync(path.join(BIN, "aip"), args, {
      cwd: WORKDIR,
      env: { ...process.env, ...CLI_ENV, AIP_SERVER: SERVER },
      input: input === undefined ? undefined : JSON.stringify(input),
      encoding: "utf8",
    });
  } catch (e) {
    const out = e as { stdout?: string; status?: number };
    if (out.stdout && out.status === 1) return out.stdout;   // an error object: the caller reads it
    throw e;
  }
}

/** `aip run`/`aip resume` with the input on stdin: the one JSON object it prints. */
export function aipJson(args: string[], input?: unknown): Record<string, unknown> {
  const full = input === undefined ? args : [...args, "--input", "-"];
  return JSON.parse(aip(full, input)) as Record<string, unknown>;
}
