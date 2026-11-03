// A skill's files into a Draft (S4): SKILL.md is parsed however invalid it is, and every other file is carried as it
// is, so an export without edits gives back the same bytes. What the Studio writes itself on export (a placeholder,
// its own source/README.md) is dropped here, since the export makes it again from the Draft.

import { FORMAT_VERSION, type Draft, type StoredFile } from "./draft";
import { PLACEHOLDER_MARKER } from "./lint";
import { NOTES_PATH, README_PATH, STUDIO_NOTE } from "./scaffold";
import { skillMdToDraft } from "./serialize";
import type { ZipFile } from "../zip";

export function importSkill(files: ZipFile[]): Draft {
  const md = files.find((f) => f.path === "SKILL.md");
  if (!md) throw new Error("the skill has no SKILL.md");
  const text = new TextDecoder().decode(md.bytes);
  const draft = skillMdToDraft(text);
  draft.origin = text;
  draft.files = files.filter((f) => f.path !== "SKILL.md" && !studioMade(f)).map(store);
  return draft;
}

/** A file the Studio writes itself on export: a placeholder, or its notes. */
export function studioMade(f: ZipFile): boolean {
  const text = new TextDecoder().decode(f.bytes);
  return text.includes(PLACEHOLDER_MARKER) || ((f.path === README_PATH || f.path === NOTES_PATH) && text.includes(STUDIO_NOTE));
}

export function store(f: ZipFile): StoredFile {
  let binary = "";
  for (let i = 0; i < f.bytes.length; i += 0x8000) binary += String.fromCharCode(...f.bytes.subarray(i, i + 0x8000));
  return { path: f.path, mode: f.mode, b64: btoa(binary) };
}

/** The files a draft carries, as the scaffold takes them. */
export function carried(draft: Draft): ZipFile[] {
  return (draft.files ?? []).map((f) => ({ path: f.path, mode: f.mode, bytes: Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0)) }));
}

// ------------------------------------------------------------------------------------------- format version

/** Recognised earlier formats and the edits each needs, as aip-spec says them (skill.py `UPGRADES`). */
const UPGRADES: Record<string, string> = {
  "0.5a1": "run `aip upgrade <folder>` (or `aip-spec upgrade <folder>`) for the mechanical part (the `start` step, no `thresholds`, `fallback: true` on each decision, the runtime block), then add outputs to each execution and client_task step and a requires block by hand",
  "0.6a0": "run `aip upgrade <folder>` (or `aip-spec upgrade <folder>`): it adds the `start` step, drops `thresholds`, sets `fallback: true` on each decision, and replaces the runtime block",
  "0.6a1": "run `aip upgrade <folder>` (or `aip-spec upgrade <folder>`): it adds the `start` step, drops `thresholds`, sets `fallback: true` on each decision, and replaces the runtime block",
};
/** Earlier formats the current one still accepts (skill.py `ACCEPTED_VERSIONS`): none, 0.8 is breaking. */
const ACCEPTED = new Set<string>([]);

/** aip-spec's own message for a skill written in another format version, or null for the current one. */
export function versionMessage(version: string): string | null {
  if (version === FORMAT_VERSION) return null;
  const upgrade = UPGRADES[version];
  if (upgrade) {
    const edits = `${version} skill: ${upgrade} (\`aip-spec runtime\` prints the ${FORMAT_VERSION} block; set \`metadata.aip-version\` to "${FORMAT_VERSION}").`;
    return ACCEPTED.has(version)
      ? `${edits} Format ${FORMAT_VERSION} still accepts ${version} skills`
      : `${edits} Format ${FORMAT_VERSION} does not accept ${version} skills; the errors below name what to edit`;
  }
  return `\`metadata.aip-version\` is \`${version}\` but this validator implements \`${FORMAT_VERSION}\`; update the skill or install a matching aip-spec version`;
}

/** Whether `aip upgrade` can move a skill of this version to the current format: the versions it recognises. */
export const canUpgrade = (version: string): boolean => version in UPGRADES;

// ------------------------------------------------------------------------------------------- aip upgrade

/** What `aip upgrade` did to a skill, as the console's process reports it (`POST /console/upgrade`). */
export interface Upgraded {
  /** The command's exit status: 0 the result validates, 1 it was written but the validator still names something,
   *  2 the skill could not be rewritten and nothing changed. */
  status: number;
  valid: boolean;
  /** What the command printed: each change made and what is left by hand. */
  output: string;
  /** The validator's issues on the result, as `aip-spec validate` prints them. */
  issues: { kind: string; message: string; severity?: string; path?: string; location?: string }[];
  /** The rewritten SKILL.md, when one was written. */
  skillMd: string | null;
}

/** How the upgrade reaches `aip upgrade`: the console's process (api/console.ts), or a stand-in for a test. */
export type Upgrader = (name: string, files: StoredFile[]) => Promise<Upgraded>;

/** The draft's imported skill run through `aip upgrade`: a new Draft from the rewritten SKILL.md, carrying the same
 *  files, and the command's report. The draft is left as it was when nothing was written. */
export async function upgradeDraft(draft: Draft, upgrader: Upgrader): Promise<{ draft: Draft; result: Upgraded }> {
  const origin = draft.origin;
  if (!origin) throw new Error("only an imported skill can be upgraded: the Studio needs its SKILL.md as it was written");
  const files: StoredFile[] = [store({ path: "SKILL.md", mode: 0o644, bytes: new TextEncoder().encode(origin) }), ...(draft.files ?? [])];
  const result = await upgrader(draft.name, files);
  if (result.skillMd === null) return { draft, result };
  const next = skillMdToDraft(result.skillMd);
  next.origin = result.skillMd;
  next.files = draft.files;
  if (draft.agentPrompt !== undefined) next.agentPrompt = draft.agentPrompt;
  return { draft: next, result };
}
