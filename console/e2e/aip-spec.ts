import { spawnSync } from "node:child_process";
import { AIP_REPO } from "./aip";

/** `aip-spec <args>` the way e2e/prepare.mjs runs it: the aip repo's environment behind `uv run`. */
export function aipSpec(args: string[]): { status: number; stdout: string; stderr: string } {
  const run = spawnSync("uv", ["run", "--quiet", "--project", AIP_REPO, "aip-spec", ...args], { encoding: "utf8" });
  return { status: run.status ?? -1, stdout: run.stdout, stderr: run.stderr };
}

export interface SpecIssue { kind: string; message: string; severity: "error" | "warning" | "info" }

/** Every issue `aip-spec validate` reports for a skill folder, with its severity (an error carries none on the wire). */
export function specIssues(dir: string): SpecIssue[] {
  const { stderr } = aipSpec(["validate", dir]);
  return stderr.split("\n").filter((l) => l.startsWith("{")).map((l) => {
    const r = JSON.parse(l) as Partial<SpecIssue> & { kind: string; message: string };
    return { ...r, severity: r.severity ?? "error" };
  });
}

/** The errors alone. */
export function specErrors(dir: string): SpecIssue[] {
  return specIssues(dir).filter((r) => r.severity === "error");
}
