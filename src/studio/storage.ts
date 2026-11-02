// The Studio's drafts in localStorage: an index (which drafts exist, which is open) and one key per draft. Every
// read and write is best effort: in a private window or with site data blocked the page still works with one draft
// in memory, and says so.

import { emptyDraft, type Draft } from "./draft";

/** The single draft S1 to S3 kept. Still read: a draft found here is moved into the index as a new draft and opened. */
export const DRAFT_KEY = "aip-console:studio:draft";
export const INDEX_KEY = "aip-console:studio:drafts";
const draftKey = (id: string) => `${DRAFT_KEY}:${id}`;

export interface DraftEntry { id: string; label: string; updated: number }
export interface Shelf { current: string; drafts: DraftEntry[] }

/** True when this browser lets the page write localStorage. */
export function storageAvailable(): boolean {
  try {
    const probe = `${INDEX_KEY}:probe`;
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

function readIndex(): Shelf | null {
  try {
    const raw = localStorage.getItem(INDEX_KEY);
    const s = raw ? (JSON.parse(raw) as Shelf) : null;
    return s && Array.isArray(s.drafts) && typeof s.current === "string" ? s : null;
  } catch {
    return null;
  }
}

function writeIndex(shelf: Shelf): boolean {
  try {
    localStorage.setItem(INDEX_KEY, JSON.stringify(shelf));
    return true;
  } catch {
    return false;
  }
}

function readDraft(key: string): Draft | null {
  try {
    const raw = localStorage.getItem(key);
    const d = raw ? (JSON.parse(raw) as Draft) : null;
    return d && Array.isArray(d.steps) && Array.isArray(d.triggerWhen) ? d : null;
  } catch {
    return null;
  }
}

function newId(shelf: Shelf | null): string {
  const taken = new Set(shelf?.drafts.map((d) => d.id));
  let id: string;
  do { id = Math.random().toString(36).slice(2, 10); } while (taken.has(id));
  return id;
}

/** The shelf and its open draft, made with one blank draft when there is none. */
export function openShelf(): { shelf: Shelf; draft: Draft } {
  let shelf = readIndex();
  const legacy = readDraft(DRAFT_KEY);
  if (legacy) {
    const added = addDraft(shelf, legacy, legacy.name || "untitled draft");
    try { localStorage.removeItem(DRAFT_KEY); } catch { /* it is read again next time, and added again */ }
    return { shelf: added, draft: legacy };
  }
  if (shelf) {
    shelf.drafts = shelf.drafts.filter((d) => d.id === shelf!.current || readDraft(draftKey(d.id)));
    const draft = shelf.drafts.some((d) => d.id === shelf!.current) ? readDraft(draftKey(shelf.current)) : null;
    if (draft) return { shelf, draft };
    if (shelf.drafts.length) {
      const next = shelf.drafts[0];
      const d = readDraft(draftKey(next.id));
      if (d) { shelf = { ...shelf, current: next.id }; writeIndex(shelf); return { shelf, draft: d }; }
    }
  }
  const draft = emptyDraft();
  return { shelf: addDraft(shelf, draft, "untitled draft"), draft };
}

/** A new draft on the shelf, opened. */
export function addDraft(shelf: Shelf | null, draft: Draft, label: string): Shelf {
  const id = newId(shelf);
  const next: Shelf = { current: id, drafts: [{ id, label, updated: Date.now() }, ...(shelf?.drafts ?? [])] };
  saveDraft(id, draft);
  writeIndex(next);
  return next;
}

/** True when the write went through. */
export function saveDraft(id: string, draft: Draft): boolean {
  try {
    localStorage.setItem(draftKey(id), JSON.stringify(draft));
  } catch {
    return false;
  }
  const shelf = readIndex();
  if (shelf) {
    const entry = shelf.drafts.find((d) => d.id === id);
    if (entry) { entry.updated = Date.now(); writeIndex(shelf); }
  }
  return true;
}

export function loadDraft(id: string): Draft | null {
  return readDraft(draftKey(id));
}

/** The shelf with `id` open. */
export function switchTo(shelf: Shelf, id: string): Shelf {
  const next = { ...shelf, current: id };
  writeIndex(next);
  return next;
}

export function renameDraft(shelf: Shelf, id: string, label: string): Shelf {
  const next = { ...shelf, drafts: shelf.drafts.map((d) => (d.id === id ? { ...d, label } : d)) };
  writeIndex(next);
  return next;
}

/** The shelf without `id`; when it was open, the next one opens (a blank one when none is left). */
export function deleteDraft(shelf: Shelf, id: string): { shelf: Shelf; draft: Draft } {
  try { localStorage.removeItem(draftKey(id)); } catch { /* best effort */ }
  const left = shelf.drafts.filter((d) => d.id !== id);
  const open = left.find((d) => d.id === shelf.current) ?? left[0];
  const draft = open ? readDraft(draftKey(open.id)) : null;
  if (open && draft) {
    const next = { current: open.id, drafts: left };
    writeIndex(next);
    return { shelf: next, draft };
  }
  const blank = emptyDraft();
  return { shelf: addDraft({ current: "", drafts: left.filter((d) => d !== open) }, blank, "untitled draft"), draft: blank };
}
