import { useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ValidationIssue } from "../api/types";
import { navigate } from "../router";
import { frontmatterName, packSkill, unpackSkill, type ZipFile } from "../zip";
import { describe, formatSize } from "./Source";

/** "download zip": the revision as `<name>@<rev>.zip`, one `<name>/` folder inside (the Agent Skills layout),
 *  packed here from the manifest and the files, with the token the page holds. */
export function DownloadZip({ name, revision }: { name: string; revision: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const reference = `${name}@${revision}`;
      save(`${reference}.zip`, packSkill(name, await revisionFiles(reference)));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className="linkish" disabled={busy} onClick={() => void download()} data-testid="download-zip">
        {busy ? "packing…" : "download zip"}
      </button>
      {error && <span className="error" role="alert"> {error}</span>}
    </>
  );
}

/** Every file of a revision, from its manifest, with the token the page holds. */
export async function revisionFiles(reference: string): Promise<ZipFile[]> {
  const manifest = await api.files(reference);
  return Promise.all(manifest.map(async (f) => ({ path: f.path, mode: f.mode, bytes: (await api.file(reference, f.path)).bytes })));
}

export function save(filename: string, bytes: Uint8Array) {
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: "application/zip" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// ------------------------------------------------------------------ upload

/** The largest zip the page unpacks and posts: the publish body carries the files as base64 in JSON. */
const MAX_ZIP = 100 * 1024 * 1024;

type Phase =
  | { at: "idle" }
  | { at: "busy"; what: string }
  | { at: "failed"; message: string; issues: ValidationIssue[]; forbidden: boolean };

/** "Publish a skill zip" (publish scope): the zip is unpacked here and its files posted to the server, which
 *  validates them and names the skill from SKILL.md. On success the page moves to the revision, with a note
 *  when it was already there (the same bytes make the same revision) or the server warned about something. */
export function UploadZip({ onPublished }: { onPublished?: () => void }) {
  const [phase, setPhase] = useState<Phase>({ at: "idle" });
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const publish = async (file: File) => {
    if (file.size > MAX_ZIP) {
      setPhase({ at: "failed", message: `${file.name} is ${formatSize(file.size)}; the console publishes zips up to ${formatSize(MAX_ZIP)}`, issues: [], forbidden: false });
      return;
    }
    setPhase({ at: "busy", what: `unpacking ${file.name}…` });
    try {
      const { files } = unpackSkill(new Uint8Array(await file.arrayBuffer()));
      const name = frontmatterName(files.find((f) => f.path === "SKILL.md")!.bytes);
      if (!name) throw new Error("SKILL.md has no `name` in its frontmatter");
      setPhase({ at: "busy", what: `publishing ${name} (${files.length} files)…` });
      const before = await api.catalog().then((all) => all.find((c) => c.name === name)?.revisions.map((r) => r.revision) ?? [], () => [] as string[]);
      const result = await api.publish(files);
      setPhase({ at: "idle" });
      onPublished?.();
      const ref = `${result.name}@${result.revision}`;
      stashPublished(ref, { existed: before.includes(result.revision), warnings: result.warnings, from: file.name });
      navigate({ page: "procedure", ref });
    } catch (e) {
      const forbidden = e instanceof ApiError && (e.status === 401 || e.status === 403);
      setPhase({ at: "failed", message: describe(e), issues: e instanceof ApiError ? e.issues : [], forbidden });
    }
  };

  const pick = (list: FileList | null) => {
    const file = list?.[0];
    if (file) void publish(file);
    if (input.current) input.current.value = "";
  };

  return (
    <section className={`upload-zip${over ? " over" : ""}`} data-testid="upload-zip"
             onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}>
      <input ref={input} type="file" accept=".zip,application/zip" aria-label="skill zip" hidden
             onChange={(e) => pick(e.target.files)} />
      <div className="actions">
        <button type="button" disabled={phase.at === "busy"} onClick={() => input.current?.click()}>Publish a skill zip…</button>
        <span className="muted small">
          {phase.at === "busy" ? phase.what
            : "or drop one here: a folder with SKILL.md, zipped. An existing name gets a new revision (the publish scope)."}
        </span>
      </div>
      {phase.at === "failed" && (
        <div className="error" role="alert" data-testid="upload-error">
          <p>Not published: {phase.message}{phase.forbidden ? ". Set a token with the publish scope on the Server page." : ""}</p>
          {phase.issues.length > 0 && <Issues issues={phase.issues} />}
        </div>
      )}
    </section>
  );
}

export function Issues({ issues }: { issues: ValidationIssue[] }) {
  return (
    <ul className="issues" data-testid="issues">
      {issues.map((i, n) => (
        <li key={n} data-severity={i.severity ?? "error"}>
          <code>{i.path}</code>{i.location ? <> at <code>{i.location}</code></> : null}: {i.message} <span className="muted">({i.kind})</span>
        </li>
      ))}
    </ul>
  );
}

/** What an upload leaves for the procedure page it moves to, read once on arrival. */
export interface PublishedNote { existed: boolean; warnings: ValidationIssue[]; from: string }

let published: { ref: string; note: PublishedNote } | null = null;

export function stashPublished(ref: string, note: PublishedNote) {
  published = { ref, note };
}

export function takePublished(ref: string): PublishedNote | null {
  if (!published || published.ref !== ref) return null;
  const { note } = published;
  published = null;
  return note;
}

/** The line the procedure page shows right after an upload landed on it. */
export function PublishedBanner({ reference }: { reference: string }) {
  const [note] = useState(() => takePublished(reference));
  if (!note) return null;
  return (
    <div className="published-note" data-testid="published-note" data-existed={note.existed ? "true" : "false"}>
      <p>
        {note.existed ? <>Already published: <code>{note.from}</code> holds the same files as this revision, so nothing changed.</>
                      : <>Published <code>{note.from}</code> as this revision.</>}
      </p>
      {note.warnings.length > 0 && <><p className="muted small">The server warned:</p><Issues issues={note.warnings} /></>}
    </div>
  );
}
