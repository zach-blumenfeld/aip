// Client-side diffing for the source view: a manifest diff by hash and a line
// diff for changed text files. Hand-rolled: procedure files are a few KB, so an
// LCS over the lines between the common prefix and suffix is instant, and it
// keeps the bundle free of a diff dependency.

import type { FileEntry } from "../api/types";

export type FileStatus = "added" | "removed" | "changed" | "unchanged";

export interface ManifestChange {
  path: string;
  status: FileStatus;
  a?: FileEntry;
  b?: FileEntry;
}

/** Every path in either manifest, sorted, with its status from A to B. */
export function diffManifests(a: FileEntry[], b: FileEntry[]): ManifestChange[] {
  const byA = new Map(a.map((f) => [f.path, f]));
  const byB = new Map(b.map((f) => [f.path, f]));
  const paths = [...new Set([...byA.keys(), ...byB.keys()])].sort();
  return paths.map((path) => {
    const fa = byA.get(path), fb = byB.get(path);
    if (!fa) return { path, status: "added", b: fb };
    if (!fb) return { path, status: "removed", a: fa };
    const same = fa.sha256 === fb.sha256 && fa.mode === fb.mode;
    return { path, status: same ? "unchanged" : "changed", a: fa, b: fb };
  });
}

export type LineOp = { kind: "equal" | "remove" | "add"; text: string; a?: number; b?: number };

/** Split keeping line numbering simple: a trailing newline does not add an empty last line. */
export function splitLines(text: string): string[] {
  const lines = text.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/** Line diff of A to B as a flat list of ops, with 1-based line numbers on each side. */
export function diffLines(aText: string, bText: string): LineOp[] {
  const a = splitLines(aText), b = splitLines(bText);
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length, endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB--; }

  const ops: LineOp[] = [];
  for (let i = 0; i < start; i++) ops.push({ kind: "equal", text: a[i], a: i + 1, b: i + 1 });
  ops.push(...middle(a.slice(start, endA), b.slice(start, endB), start + 1, start + 1));
  for (let i = endA, j = endB; i < a.length; i++, j++) ops.push({ kind: "equal", text: a[i], a: i + 1, b: j + 1 });
  return ops;
}

const MAX_CELLS = 4_000_000;

function middle(a: string[], b: string[], a0: number, b0: number): LineOp[] {
  const ops: LineOp[] = [];
  if (a.length === 0 || b.length === 0 || a.length * b.length > MAX_CELLS) {
    // Nothing in common to find, or too big for the table: show the block as replaced.
    a.forEach((text, i) => ops.push({ kind: "remove", text, a: a0 + i }));
    b.forEach((text, j) => ops.push({ kind: "add", text, b: b0 + j }));
    return ops;
  }
  // lcs[i][j] = length of the LCS of a[i..] and b[j..].
  const w = b.length + 1;
  const lcs = new Uint32Array((a.length + 1) * w);
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i * w + j] = a[i] === b[j] ? lcs[(i + 1) * w + j + 1] + 1 : Math.max(lcs[(i + 1) * w + j], lcs[i * w + j + 1]);
    }
  }
  let i = 0, j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      ops.push({ kind: "equal", text: a[i], a: a0 + i, b: b0 + j }); i++; j++;
    } else if (i < a.length && (j >= b.length || lcs[(i + 1) * w + j] >= lcs[i * w + j + 1])) {
      ops.push({ kind: "remove", text: a[i], a: a0 + i }); i++;
    } else {
      ops.push({ kind: "add", text: b[j], b: b0 + j }); j++;
    }
  }
  return ops;
}

/** Decode as UTF-8 text, or null when the bytes are not text (undecodable, or a NUL byte). */
export function asText(bytes: Uint8Array): string | null {
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return text.includes("\0") ? null : text;
  } catch {
    return null;
  }
}
