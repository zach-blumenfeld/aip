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

function studioMade(f: ZipFile): boolean {
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
  "0.5a1": "add outputs to each execution and client_task step, a requires block, and regenerate the runtime block",
  "0.6a0": "regenerate the runtime block (only its heading changed) and bump the version; nothing else changes",
};
const ACCEPTED = new Set(["0.6a0"]);

/** aip-spec's own message for a skill written in another format version, or null for the current one. */
export function versionMessage(version: string): string | null {
  if (version === FORMAT_VERSION) return null;
  const upgrade = UPGRADES[version];
  if (upgrade) {
    const edits = `${version} skill: ${upgrade} (\`aip-spec runtime\` prints the ${FORMAT_VERSION} block; set \`metadata.aip-version\` to "${FORMAT_VERSION}").`;
    return ACCEPTED.has(version)
      ? `${edits} Format ${FORMAT_VERSION} still accepts ${version} skills`
      : `${edits} Format ${FORMAT_VERSION} does not accept ${version} skills; any \`missing_outputs\` and \`missing_requires\` errors below name the steps to edit`;
  }
  return `\`metadata.aip-version\` is \`${version}\` but this validator implements \`${FORMAT_VERSION}\`; update the skill or install a matching aip-spec version`;
}
