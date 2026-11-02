import { spawnSync } from "node:child_process";
import { AIP_REPO } from "./aip";

/** `aip-spec <args>` the way e2e/prepare.mjs runs it: the aip repo's environment behind `uv run`. */
export function aipSpec(args: string[]): { status: number; stdout: string; stderr: string } {
  const run = spawnSync("uv", ["run", "--quiet", "--project", AIP_REPO, "aip-spec", ...args], { encoding: "utf8" });
  return { status: run.status ?? -1, stdout: run.stdout, stderr: run.stderr };
}

export interface SpecIssue { kind: string; message: string; severity?: string }

/** The errors `aip-spec validate` reports for a skill folder (warnings are left out). */
export function specErrors(dir: string): SpecIssue[] {
  const { stderr } = aipSpec(["validate", dir]);
  const records = stderr.split("\n").filter((l) => l.startsWith("{")).map((l) => JSON.parse(l) as SpecIssue);
  return records.filter((r) => r.severity !== "warning");
}
