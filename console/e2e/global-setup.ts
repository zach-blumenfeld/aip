import { AGENT, BILLING, DYNAMIC, FIRST_REVISION_DIR, FIXED, SECOND_REVISION_DIR, TRIAGE, aip, folderOf } from "./aip";

// Runs after Playwright has started the servers (and e2e/prepare.mjs has written the folders). Publishing
// merges a bundle by its id, so the same folder always lands on the same revision: v1 then v2 fixes which
// revision of billing_support_agent is the latest.
export default async function globalSetup(): Promise<void> {
  const publish = (folder: string, expected: string) => {
    const out = aip(["publish", folder]).trim();
    if (!out.startsWith(expected)) throw new Error(`publishing ${folder} should have printed ${expected}…, and printed:\n${out}`);
  };
  publish(FIRST_REVISION_DIR, `${AGENT}@1`);
  publish(SECOND_REVISION_DIR, `${AGENT}@2`);
  publish(folderOf("billing-support"), `${BILLING}@1`);
  publish(folderOf("fixed-policy"), `${FIXED}@1`);
  publish(folderOf("dynamic-policy"), `${DYNAMIC}@1`);
  publish(folderOf("ticket-triage"), `${TRIAGE}@1`);
}
