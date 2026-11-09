import { CHECKED, CHECKED_REVISION_DIR, FIRST_REVISION_DIR, SECOND_REVISION_DIR, aip } from "./aip";

export { CHANGED_FILE, NEW_LINE, OLD_LINE, SECOND_REVISION_DIR } from "./aip";

// Runs after Playwright has started the servers (and e2e/prepare.mjs has written the two folders).
// Publishing is idempotent: the same folder always yields the same revision, so v1 then v2 fixes which
// revision is newest.
export default async function globalSetup(): Promise<void> {
  const first = aip(["publish", FIRST_REVISION_DIR]);
  if (!/billing-support@/.test(first)) throw new Error(`publish did not return a revision:\n${first}`);
  const second = aip(["publish", SECOND_REVISION_DIR]);
  if (!/billing-support@/.test(second)) throw new Error(`second publish did not return a revision:\n${second}`);
  if (second.trim() === first.trim()) throw new Error("the second publish yielded the same revision as the first");
  const checked = aip(["publish", CHECKED_REVISION_DIR]);
  if (!new RegExp(`${CHECKED}@`).test(checked)) throw new Error(`publishing ${CHECKED} did not return a revision:\n${checked}`);
}
