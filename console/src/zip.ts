// Skill zips, packed and unpacked in the browser (fflate): the Agent Skills layout, one top-level `<name>/`
// folder with SKILL.md inside. Download builds one from a revision's manifest and files; upload turns one into
// the files `POST /catalog` takes. The server names the skill from SKILL.md's frontmatter, so the zip's folder
// name is never read: an existing name gets a new revision, the same bytes the same revision.

import { strToU8, unzipSync, zipSync, type Zippable } from "fflate";

export interface ZipFile { path: string; bytes: Uint8Array; mode: number }

/** `<name>/<path>` for every file, with its Unix mode, deterministic (fixed mtime) like the server's tar. */
export function packSkill(name: string, files: ZipFile[]): Uint8Array {
  const entries: Zippable = {};
  for (const f of [...files].sort((a, b) => (a.path < b.path ? -1 : 1))) {
    entries[`${name}/${f.path}`] = [f.bytes, { os: 3, attrs: ((f.mode & 0o777) | 0o100000) << 16, mtime: EPOCH }];
  }
  return zipSync(entries, { level: 6, os: 3, mtime: EPOCH });
}

// DOS time, which zip stores, is local: fflate refuses a date before 1980 in this machine's zone.
const EPOCH = new Date(1980, 0, 1, 12);

// What the server's snapshot ignores on disk, plus what zip tools add (`__MACOSX/`): dropped before upload.
const IGNORE_DIRS = new Set([".git", "__pycache__", ".aip", "__MACOSX"]);
const IGNORE_FILES = new Set([".DS_Store", ".aip-manifest.json"]);
const IGNORE_SUFFIXES = [".pyc"];

export interface Unpacked {
  files: ZipFile[];
  /** The top-level folder every path was under, when there was one. */
  folder: string | null;
}

/** The skill's files from a zip: SKILL.md at the root, or inside exactly one top-level folder (the Agent Skills
 *  layout), which is stripped. Throws with a message for the page when the zip is not a skill. */
export function unpackSkill(zip: Uint8Array): Unpacked {
  let raw: Record<string, Uint8Array>;
  try {
    raw = unzipSync(zip);
  } catch (e) {
    throw new Error(`not a zip file (${e instanceof Error ? e.message : String(e)})`);
  }
  const modes = unixModes(zip);
  const kept: ZipFile[] = [];
  for (const [entry, bytes] of Object.entries(raw)) {
    if (entry.endsWith("/")) continue;                      // a directory entry
    const parts = entry.split("/");
    if (parts.some((p) => IGNORE_DIRS.has(p)) || IGNORE_FILES.has(parts[parts.length - 1])) continue;
    if (IGNORE_SUFFIXES.some((s) => entry.endsWith(s))) continue;
    if (parts.some((p) => p === "" || p === "." || p === "..")) throw new Error(`unsafe path in the zip: ${entry}`);
    kept.push({ path: entry, bytes, mode: modes.get(entry) ?? 0o644 });
  }
  if (kept.length === 0) throw new Error("the zip holds no files");

  let folder: string | null = null;
  if (!kept.some((f) => f.path === "SKILL.md")) {
    const tops = new Set(kept.map((f) => f.path.split("/")[0]));
    if (tops.size !== 1) throw new Error(`no SKILL.md at the top of the zip, and ${tops.size} top-level folders (${[...tops].sort().join(", ")}) instead of one`);
    folder = [...tops][0];
    if (!kept.some((f) => f.path === `${folder}/SKILL.md`)) throw new Error(`no SKILL.md in the zip's ${folder}/ folder`);
    for (const f of kept) f.path = f.path.slice(folder.length + 1);
  }
  kept.sort((a, b) => (a.path < b.path ? -1 : 1));
  return { files: kept, folder };
}

/** The `name` of SKILL.md's frontmatter, or null when there is none: what the server will publish it as. */
export function frontmatterName(skillMd: Uint8Array): string | null {
  const text = new TextDecoder().decode(skillMd);
  const m = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text);
  if (!m) return null;
  const line = /^name:\s*["']?([^"'\s#]+)["']?\s*$/m.exec(m[1]);
  return line ? line[1] : null;
}

export const utf8 = strToU8;

// ------------------------------------------------------------------ modes, from the central directory
// fflate's unzip gives the bytes only. The mode is in each central-directory entry's external attributes
// when the entry says it was made on Unix (version-made-by high byte 3), which is what packSkill writes.

function unixModes(zip: Uint8Array): Map<string, number> {
  const modes = new Map<string, number>();
  const view = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
  // The end-of-central-directory record: signature 0x06054b50, within the last 64KB + 22 bytes.
  let eocd = -1;
  for (let i = zip.length - 22; i >= Math.max(0, zip.length - 65557); i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) return modes;
  const count = view.getUint16(eocd + 10, true);
  let at = view.getUint32(eocd + 16, true);
  const decoder = new TextDecoder();
  for (let n = 0; n < count && at + 46 <= zip.length; n++) {
    if (view.getUint32(at, true) !== 0x02014b50) break;
    const madeBy = view.getUint8(at + 5);
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    const external = view.getUint32(at + 38, true);
    const name = decoder.decode(zip.subarray(at + 46, at + 46 + nameLength));
    if (madeBy === 3 || madeBy === 19) {
      const mode = (external >>> 16) & 0o777;
      if (mode) modes.set(name, mode);
    }
    at += 46 + nameLength + extraLength + commentLength;
  }
  return modes;
}
