// `npm run e2e`, before any server starts (the first webServer command in playwright.config.ts runs this):
// a fresh .aip-e2e/ with
//   bin/aip          this repository's CLI (AIP_REPO, default `..`: the console lives in the aip repo) behind
//                    `uv run`, put first on the consoles' PATH, the way an installed `aip` would be
//   v1/billing-support-agent, v2/billing-support-agent
//                    examples/language/billing-support-agent, whose `triage` is a Task_Agent, so it runs with no
//                    decision model; its escalate script files each ticket under the run's working directory (and
//                    can fail or stall on request, below); v2 changes one line of the policy
//   billing-support  the same procedure with `triage` as a Decide, for the decision model (e2e/model.mjs)
//   fixed-policy, dynamic-policy, ticket-triage
//                    the loop examples as shipped
//   draft/billing-support-agent
//                    v1 with one description reworded: another bundle, never published, so its runs are a draft's
//   store/ home/ work/ work-folder/
//                    the server's store, the CLI's run files and bundle cache, and the two consoles' working directories
// The diff spec reads the policy lines from e2e/aip.ts, which repeats them.
import { chmodSync, cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const here = import.meta.dirname;
const E2E = path.resolve(here, "..", ".aip-e2e");
const repo = path.resolve(process.env.AIP_REPO ?? path.join(here, "..", ".."));
const examples = path.join(repo, "examples", "language");
if (!existsSync(path.join(repo, "pyproject.toml")) || !existsSync(path.join(examples, "billing-support-agent", "procedure.aip"))) {
  console.error(`prepare: AIP_REPO=${repo} is not the aip repo (no pyproject.toml, or no examples/language); set AIP_REPO`);
  process.exit(1);
}

const OLD_LINE = "- Refunds for other reasons are honored within 30 days of purchase.";
const NEW_LINE = "- Refunds for other reasons are honored within 45 days of purchase.";
const OLD_DESCRIPTION = "Turn an inbound billing message";
const NEW_DESCRIPTION = "Turn an incoming billing message";

// The escalate script of the e2e procedures. Its ticket file is how the specs see that the script ran on the
// console's machine, in the run's working directory (AIP_WORKDIR). A message containing "[outage]" fails
// while that directory holds `ticket-service-down`; one containing "[slow]" sleeps, for cancel.
const ESCALATE = `#!/usr/bin/env python3
"""Open a tier-2 ticket for an angry billing customer and file it under the run's working directory.

stdin:  {"state": {"message": str, "tone": {...}}, "assets": {"config": str}, "expects": {...}}
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

/** `text` with `from` replaced once by `to`; the harness stops when the example no longer holds `from`. */
function replaced(file, from, to) {
  const text = readFileSync(file, "utf8");
  if (!text.includes(from)) {
    console.error(`prepare: ${file} no longer contains ${JSON.stringify(from)}, which the e2e fixtures change`);
    process.exit(1);
  }
  writeFileSync(file, text.replace(from, to));
}

rmSync(E2E, { recursive: true, force: true });
for (const dir of ["bin", "store", "home", "work", "work-folder"]) mkdirSync(path.join(E2E, dir), { recursive: true });

const aip = path.join(E2E, "bin", "aip");
writeFileSync(aip, `#!/bin/sh\nexec uv run --quiet --project "${repo}" aip "$@"\n`);
chmodSync(aip, 0o755);

const copy = (example, ...to) => {
  const dir = path.join(E2E, ...to);
  cpSync(path.join(examples, example), dir, { recursive: true });
  return dir;
};

const v1 = copy("billing-support-agent", "v1", "billing-support-agent");
writeFileSync(path.join(v1, "scripts", "escalate.py"), ESCALATE);

const v2 = path.join(E2E, "v2", "billing-support-agent");
cpSync(v1, v2, { recursive: true });
replaced(path.join(v2, "assets", "policy.md"), OLD_LINE, NEW_LINE);

const draft = path.join(E2E, "draft", "billing-support-agent");
cpSync(v1, draft, { recursive: true });
replaced(path.join(draft, "procedure.aip"), OLD_DESCRIPTION, NEW_DESCRIPTION);

const model = copy("billing-support", "billing-support");
writeFileSync(path.join(model, "scripts", "escalate.py"), ESCALATE);
for (const example of ["fixed-policy", "dynamic-policy", "ticket-triage"]) copy(example, example);

console.log(`prepare: ${E2E} ready (aip from ${repo})`);
