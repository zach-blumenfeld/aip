import { useEffect, useMemo, useState } from "react";
import { allFiles, describe, graphOf } from "../api/client";
import type { BundleFile, BundleGraph } from "../api/types";
import { Code, isProcedureSource } from "../highlight/Code.tsx";
import { bundleOf, href } from "../router";
import { DraftBadge } from "./Record";

/** What a bundle was compiled from: `procedure.aip`, byte for byte as it was stored, in the colours of the
 *  grammar the VS Code extension ships, and the files beside it. All of it comes with the bundle's graph. */
export function Source({ reference, path }: { reference: string; path?: string }) {
  const [bundle, setBundle] = useState<BundleGraph | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBundle(null);
    setError(null);
    graphOf(reference).then(setBundle).catch((e: unknown) => setError(describe(e)));
  }, [reference]);

  const files = useMemo(() => (bundle ? allFiles(bundle) : []), [bundle]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (bundle === null) return <p className="muted">Loading the source of {reference}…</p>;
  const total = files.reduce((n, f) => n + f.size, 0);
  const open = path ?? "procedure.aip";
  const file = files.find((f) => f.path === open);

  return (
    <article className="source">
      <nav className="crumbs">
        <a href={href({ page: "catalog" })}>catalog</a> / <a href={href({ page: "procedure", ref: reference })}><code>{bundle.name}</code></a> / source
        {path && <> / <code>{path}</code></>}
      </nav>
      <h1>{bundle.name} <span className="muted rev">source{bundle.revision ? ` @${bundle.revision}` : ""}</span> <DraftBadge draft={bundle.draft} /></h1>
      <p className="muted">
        {files.length} files, {formatSize(total)} · bundle <code title={bundle.bundle_id}>{bundle.bundle_id.slice(0, 12)}</code>
        {!bundleOf(reference) && <> · <a href={href({ page: "diff", name: bundle.name })}>compare revisions</a></>}
        {" "}· <code>aip get {bundle.revision ? `${bundle.name}@${bundle.revision}` : bundle.name} --out DIR</code> writes this folder
      </p>

      <div className="source-grid">
        <table aria-label="files" className="compact manifest">
          <thead><tr><th>path</th><th>size</th><th>sha256</th><th>mode</th></tr></thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.path} aria-current={f.path === open ? "true" : undefined} data-testid="file-row" data-path={f.path}>
                <td><a href={href({ page: "source", ref: reference, path: f.path })}><code>{f.path}</code></a></td>
                <td className="num">{formatSize(f.size)}</td>
                <td>{f.sha256 ? <code title={f.sha256}>{f.sha256.slice(0, 12)}</code> : <span className="muted" title="The source is the bundle's own text; the bundle id is its hash with the files'.">—</span>}</td>
                <td><code>{(f.mode & 0o777).toString(8)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
        {file ? <FileViewer file={file} /> : <p className="error" role="alert">No file {open} in this bundle.</p>}
      </div>
    </article>
  );
}

function FileViewer({ file }: { file: BundleFile }) {
  // A file that is not UTF-8 text is kept as base64: offered as a download, not shown.
  const download = useMemo(() => {
    if (file.text !== null || file.base64 === null) return null;
    const bytes = Uint8Array.from(atob(file.base64), (c) => c.charCodeAt(0));
    return URL.createObjectURL(new Blob([bytes as BlobPart]));
  }, [file]);
  useEffect(() => () => { if (download) URL.revokeObjectURL(download); }, [download]);

  return (
    <section className="file-view" aria-label="file">
      <h2><code>{file.path}</code> <span className="muted">· {formatSize(file.size)}</span></h2>
      {file.text === null ? (
        <p data-testid="binary-file">
          Not text. <a href={download ?? "#"} download={file.path.split("/").pop()}>Download {formatSize(file.size)}</a>
        </p>
      ) : (
        <Code text={file.text} aip={isProcedureSource(file.path)} />
      )}
    </section>
  );
}

export function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
