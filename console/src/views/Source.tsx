import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type FileBytes } from "../api/client";
import type { FileEntry } from "../api/types";
import { asText, splitLines } from "../diff/lines";
import { href } from "../router";
import { DownloadZip } from "./Zip";

/** View 2a: the file manifest of a revision and a viewer for one file. */
export function Source({ reference, path }: { reference: string; path?: string }) {
  const [files, setFiles] = useState<FileEntry[] | null>(null);
  const [revision, setRevision] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const name = reference.split("@")[0];

  useEffect(() => {
    setFiles(null);
    setRevision(null);
    setError(null);
    api.files(reference).then(setFiles).catch((e: unknown) => setError(describe(e)));
    // The zip is named after the exact revision, which a bare name or `@latest` leaves to the catalog to say.
    api.info(reference).then((info) => setRevision(info.revision)).catch(() => undefined);
  }, [reference]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (files === null) return <p className="muted">Loading files of {reference}…</p>;
  const total = files.reduce((n, f) => n + f.size, 0);

  return (
    <article className="source">
      <nav className="crumbs">
        <a href={href({ page: "catalog" })}>catalog</a> / <a href={href({ page: "procedure", ref: reference })}><code>{reference}</code></a> / files
        {path && <> / <code>{path}</code></>}
      </nav>
      <h1>{name} <span className="muted rev">source{reference.includes("@") ? ` @${reference.split("@")[1]}` : ""}</span></h1>
      <p className="muted">
        {files.length} files, {formatSize(total)} · <a href={href({ page: "diff", name })}>compare revisions</a>
        {revision && <> · <DownloadZip name={name} revision={revision} /></>}
      </p>

      <div className="source-grid">
        <table aria-label="file manifest" className="compact manifest">
          <thead><tr><th>path</th><th>size</th><th>sha256</th><th>mode</th></tr></thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.path} aria-current={f.path === path ? "true" : undefined}>
                <td><a href={href({ page: "source", ref: reference, path: f.path })}><code>{f.path}</code></a></td>
                <td className="num">{formatSize(f.size)}</td>
                <td><code title={f.sha256}>{f.sha256.slice(0, 12)}</code></td>
                <td><code>{(f.mode & 0o777).toString(8)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
        {path ? <FileViewer reference={reference} path={path} entry={files.find((f) => f.path === path)} />
              : <p className="muted">Pick a file to view it.</p>}
      </div>
    </article>
  );
}

function FileViewer({ reference, path, entry }: { reference: string; path: string; entry?: FileEntry }) {
  const [data, setData] = useState<FileBytes | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.file(reference, path).then(setData).catch((e: unknown) => setError(describe(e)));
  }, [reference, path]);

  const text = useMemo(() => (data ? asText(data.bytes) : null), [data]);
  // A blob URL carries the bytes we already fetched with the token, so the download
  // needs no second, unauthenticated request.
  const downloadUrl = useMemo(
    () => (data && text === null ? URL.createObjectURL(new Blob([data.bytes as BlobPart], { type: data.mediaType })) : null),
    [data, text],
  );
  useEffect(() => () => { if (downloadUrl) URL.revokeObjectURL(downloadUrl); }, [downloadUrl]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p className="muted">Loading {path}…</p>;
  const size = entry?.size ?? data.bytes.length;

  return (
    <section className="file-view" aria-label="file">
      <h2><code>{path}</code> <span className="muted">· {formatSize(size)} · {data.mediaType}</span></h2>
      {text === null ? (
        <p data-testid="binary-file">
          Binary file. <a href={downloadUrl ?? "#"} download={path.split("/").pop()}>Download {formatSize(size)}</a>
        </p>
      ) : (
        <Code text={text} />
      )}
    </section>
  );
}

/** Monospace text with line numbers from CSS counters. */
export function Code({ text }: { text: string }) {
  const lines = splitLines(text);
  return (
    <ol className="code" data-testid="file-text">
      {lines.map((line, i) => <li key={i}>{line === "" ? "​" : line}</li>)}
    </ol>
  );
}

export function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function describe(e: unknown): string {
  return e instanceof ApiError ? `${e.kind}: ${e.message}` : String(e);
}
