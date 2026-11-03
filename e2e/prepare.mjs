// `npm run e2e`, before any server starts (the first webServer command in playwright.config.ts runs this):
// a fresh .aip-e2e/ with
//   bin/aip          the sibling aip repo's CLI (AIP_REPO, default ../aip) behind `uv run`, put first on the
//                    consoles' PATH, the way an installed `aip` would be; `aip-spec` and `python` beside it, for
//                    the Studio's agent checks
//   example/billing-support
//                    aip-spec's example as shipped, for the lint specs
//   v1/billing-support, v2/billing-support
//                    the example with its router's confidence check removed (every decision the e2e CLI drives is
//                    answered by hand, which records no confidence, and the check would send every run to escalate)
//                    and an escalate script that files each ticket under the run's working directory (and can fail
//                    or stall on request, below); v2 changes one line of the policy
//   checked/billing-checked
//                    the example as shipped under another name, check included, with the same escalate script
//   root/ home/ work/ work-folder/
//                    the server's backend, the CLI's run files, and the two consoles' working directories
// The diff spec reads the policy lines from e2e/aip.ts, which repeats them.
import { execFileSync } from "node:child_process";
import { chmodSync, cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const here = import.meta.dirname;
const E2E = path.resolve(here, "..", ".aip-e2e");
const repo = path.resolve(process.env.AIP_REPO ?? path.join(here, "..", "..", "aip"));
if (!existsSync(path.join(repo, "pyproject.toml"))) {
  console.error(`prepare: AIP_REPO=${repo} is not the aip repo (no pyproject.toml); set AIP_REPO`);
  process.exit(1);
}

const OLD_LINE = "- Refunds for other reasons are honored within 30 days of purchase.";
const NEW_LINE = "- Refunds for other reasons are honored within 45 days of purchase.";

// The escalate script of the e2e revisions. Its ticket file is how the specs see that the script ran on the
// console's machine, in the run's working directory (AIP_WORKDIR). A message containing "[outage]" fails
// while that directory holds `ticket-service-down`; one containing "[slow]" sleeps, for cancel.
const ESCALATE = `#!/usr/bin/env python3
"""Open a tier-2 ticket for an angry billing customer and file it under the run's working directory.

stdin:  {"state": {"message": str, "tone": str}, "assets": {"config": str}, "expects": {...}}
stdout: {"ticket_id": int, "queue": str}
"""
import hashlib
import json
import os
import sys
import time

payload = json.load(sys.stdin)
state = payload["state"]
config = json.loads(payload["assets"]["config"])
workdir = os.environ.get("AIP_WORKDIR", ".")

if "[outage]" in state["message"] and os.path.exists(os.path.join(workdir, "ticket-service-down")):
    print("ticket service unreachable", file=sys.stderr)
    sys.exit(1)
if "[slow]" in state["message"]:
    time.sleep(60)

ticket_id = int(hashlib.sha256(state["message"].encode()).hexdigest()[:8], 16) % 100_000
os.makedirs(os.path.join(workdir, "tickets"), exist_ok=True)
with open(os.path.join(workdir, "tickets", f"{ticket_id}.json"), "w") as f:
    json.dump({"ticket_id": ticket_id, "queue": config["queue"], "message": state["message"]}, f)
json.dump({"ticket_id": ticket_id, "queue": config["queue"]}, sys.stdout)
`;

rmSync(E2E, { recursive: true, force: true });
for (const dir of ["bin", "root", "home", "work", "work-folder"]) mkdirSync(path.join(E2E, dir), { recursive: true });

const aip = path.join(E2E, "bin", "aip");
writeFileSync(aip, `#!/bin/sh\nexec uv run --quiet --project "${repo}" --group dev aip "$@"\n`);
chmodSync(aip, 0o755);
// The Studio's agent checks (S6a) run `aip-spec validate` and each script under `python`, from the console's PATH.
for (const [name, program] of [["aip-spec", "aip-spec"], ["python", "python"]]) {
  const shim = path.join(E2E, "bin", name);
  writeFileSync(shim, `#!/bin/sh\nexec uv run --quiet --project "${repo}" ${program} "$@"\n`);
  chmodSync(shim, 0o755);
}

execFileSync("uv", ["run", "--quiet", "--project", repo, "aip-spec", "example", "billing-support", "--out", path.join(E2E, "example")],
             { stdio: "inherit" });
const example = path.join(E2E, "example", "billing-support");
const v1 = path.join(E2E, "v1", "billing-support");
cpSync(example, v1, { recursive: true });
writeFileSync(path.join(v1, "scripts", "escalate.py"), ESCALATE);
// The router's check and the comment above it: two lines of the shipped example.
const CHECK = /^    # Checked before the branches.*\n    confidence: \{key: tone_confidence, below: 0\.6, to: escalate\}\n/m;
const skillMd = readFileSync(path.join(v1, "SKILL.md"), "utf8");
if (!CHECK.test(skillMd)) {
  console.error("prepare: the example's SKILL.md no longer holds the router check these lines remove");
  process.exit(1);
}
writeFileSync(path.join(v1, "SKILL.md"), skillMd.replace(CHECK, ""));

// The example as shipped, check included, under its own name (the validator wants the folder named after the skill).
const checked = path.join(E2E, "checked", "billing-checked");
cpSync(example, checked, { recursive: true });
writeFileSync(path.join(checked, "scripts", "escalate.py"), ESCALATE);
// Its own description too, so the catalog search specs still rank billing-support first for "refund".
writeFileSync(path.join(checked, "SKILL.md"), readFileSync(path.join(checked, "SKILL.md"), "utf8")
  .replace(/^name: billing-support$/m, "name: billing-checked")
  .replace(/^description: .*$/m, "description: The billing example as shipped, its router checking the decision model's confidence. Use in the console's tests."));

// The folder must still be called billing-support: the validator checks the name.
const v2 = path.join(E2E, "v2", "billing-support");
cpSync(v1, v2, { recursive: true });
const policy = path.join(v2, "assets", "policy.md");
const text = readFileSync(policy, "utf8");
if (!text.includes(OLD_LINE)) {
  console.error("prepare: assets/policy.md no longer contains the line the diff spec changes");
  process.exit(1);
}
writeFileSync(policy, text.replace(OLD_LINE, NEW_LINE));
console.log(`prepare: ${E2E} ready (aip from ${repo})`);
