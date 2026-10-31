import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { isFolderMode } from "../api/console";
import type { Shelf } from "../studio/storage";
import { unpackSkill, type ZipFile } from "../zip";

interface Props {
  shelf: Shelf;
  onSwitch: (id: string) => void;
  onNew: () => void;
  onRename: (label: string) => void;
  onDelete: () => void;
  onReset: () => void;
  onImport: (files: ZipFile[], from: string) => void;
  onImportError: (message: string) => void;
  onImportRef: (ref: string) => void;
}

/** The drafts this browser keeps: pick one, start a new one, rename, delete or reset the open one, or import a skill
 *  (a zip, or a catalog revision when a server is behind the console) as a new draft. Delete and reset ask once more
 *  in the bar itself, not in a browser dialog. */
export function DraftsBar({ shelf, onSwitch, onNew, onRename, onDelete, onReset, onImport, onImportError, onImportRef }: Props) {
  const current = shelf.drafts.find((d) => d.id === shelf.current);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"delete" | "reset" | null>(null);
  const [ref, setRef] = useState("");
  const [names, setNames] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const folder = isFolderMode();

  useEffect(() => { setRenaming(null); setConfirm(null); }, [shelf.current]);
  useEffect(() => {
    if (folder) return;
    api.catalog().then((all) => setNames(all.filter((c) => c.latest).map((c) => c.name)), () => setNames([]));
  }, [folder]);

  const pick = async (file: File | undefined) => {
    if (input.current) input.current.value = "";
    if (!file) return;
    try {
      onImport(unpackSkill(new Uint8Array(await file.arrayBuffer())).files, file.name);
    } catch (e) {
      onImportError(`Could not import ${file.name}: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="studio-drafts" data-testid="studio-drafts">
      <div className="studio-bar">
        <label>
          draft{" "}
          <select aria-label="draft" value={shelf.current} onChange={(e) => onSwitch(e.target.value)}>
            {shelf.drafts.map((d) => <option key={d.id} value={d.id}>{d.label || "untitled draft"}</option>)}
          </select>
        </label>
        {renaming === null ? (
          <button onClick={() => setRenaming(current?.label ?? "")}>rename</button>
        ) : (
          <form className="row" onSubmit={(e) => { e.preventDefault(); onRename(renaming.trim() || "untitled draft"); setRenaming(null); }}>
            <input type="text" aria-label="draft name" value={renaming} autoFocus onChange={(e) => setRenaming(e.target.value)} />
            <button type="submit">save name</button>
            <button type="button" onClick={() => setRenaming(null)}>cancel</button>
          </form>
        )}
        <button onClick={onNew}>new draft</button>
        {confirm === null ? (
          <>
            <button onClick={() => setConfirm("reset")}>reset</button>
            <button className="danger" onClick={() => setConfirm("delete")}>delete draft</button>
          </>
        ) : (
          <span className="row" role="group" aria-label={`confirm ${confirm}`}>
            <span>{confirm === "reset" ? "Empty this draft? Its steps and settings are lost." : `Delete “${current?.label || "untitled draft"}”? It cannot be undone.`}</span>
            <button className="danger" onClick={() => { setConfirm(null); if (confirm === "reset") onReset(); else onDelete(); }}>
              {confirm === "reset" ? "yes, reset" : "yes, delete"}
            </button>
            <button onClick={() => setConfirm(null)}>cancel</button>
          </span>
        )}
      </div>
      <div className="studio-bar">
        <input ref={input} type="file" accept=".zip,application/zip" aria-label="import skill zip" hidden onChange={(e) => void pick(e.target.files?.[0])} />
        <button onClick={() => input.current?.click()}>Import a skill zip…</button>
        {!folder && (
          <form className="row" onSubmit={(e) => { e.preventDefault(); if (ref.trim()) onImportRef(ref.trim()); }}>
            <input type="text" list="studio-catalog-names" aria-label="catalog reference" placeholder="name or name@revision" value={ref} onChange={(e) => setRef(e.target.value)} />
            <datalist id="studio-catalog-names">{names.map((n) => <option key={n} value={n} />)}</datalist>
            <button type="submit" disabled={!ref.trim()}>Import from catalog</button>
          </form>
        )}
      </div>
    </div>
  );
}
