import { useEffect, useMemo, useState } from "react";
import { allFiles, api, describe } from "../api/client";
import type { BundleFile, CatalogEntry } from "../api/types";
import { diffLines, diffManifests, type LineOp, type ManifestChange } from "../diff/lines";
import { href, navigate } from "../router";
import { formatSize } from "./Source";

/** Two revisions of one name compared file by file (procedure.aip among them), with a line diff per changed text file. */
export function Diff({ name, a, b }: { name: string; a?: string; b?: string }) {
  const [entry, setEntry] = useState<CatalogEntry | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.catalog().then((all) => {
      const found = all.find((c) => c.name === name);
      if (!found) setError(`not_found: no procedure named ${name}`);
      else setEntry(found);
    }).catch((e: unknown) => setError(describe(e)));
  }, [name]);

  // Without an explicit pair, compare the revision the name resolves to with the one published before it.
  useEffect(() => {
    if (!entry || (a && b)) return;
    const revs = entry.revisions.map((r) => r.revision);
    if (revs.length === 0) return;
    const to = b ?? entry.resolves ?? revs[0];
    const idx = revs.indexOf(to);
    const from = a ?? revs[idx + 1] ?? revs[idx - 1] ?? to;
    navigate({ page: "diff", name, a: from, b: to });
  }, [entry, name, a, b]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!entry || !a || !b) return <p className="muted">Loading revisions of {name}…</p>;

  const pick = (side: "a" | "b", value: string) => navigate({ page: "diff", name, a: side === "a" ? value : a, b: side === "b" ? value : b });

  return (
    <article className="diff">
      <nav className="crumbs">
        <a href={href({ page: "catalog" })}>catalog</a> / <a href={href({ page: "procedure", ref: name })}><code>{name}</code></a> / diff
      </nav>
      <h1>{name} <span className="muted rev">diff</span></h1>
      <div className="diff-pickers">
        <RevisionSelect label="from" entry={entry} value={a} onChange={(v) => pick("a", v)} />
        <span className="muted">→</span>
        <RevisionSelect label="to" entry={entry} value={b} onChange={(v) => pick("b", v)} />
        <button type="button" onClick={() => navigate({ page: "diff", name, a: b, b: a })}>swap</button>
      </div>
      <FilesDiff name={name} a={a} b={b} />
    </article>
  );
}

function RevisionSelect({ label, entry, value, onChange }: { label: string; entry: CatalogEntry; value: string; onChange: (v: string) => void }) {
  return (
    <label>
      {label}{" "}
      <select aria-label={`${label} revision`} value={value} onChange={(e) => onChange(e.target.value)}>
        {entry.revisions.map((r) => (
          <option key={r.revision} value={r.revision}>
            {r.revision}{r.revision === entry.pinned ? " · pinned" : ""}{r.revision === entry.latest ? " · latest" : ""}
            {r.retired ? " · retired" : ""} — {r.published_at.slice(0, 10)}
          </option>
        ))}
      </select>
    </label>
  );
}

function FilesDiff({ name, a, b }: { name: string; a: string; b: string }) {
  const [sides, setSides] = useState<[BundleFile[], BundleFile[]] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSides(null);
    setError(null);
    Promise.all([api.graph(`${name}@${a}`), api.graph(`${name}@${b}`)])
      .then(([ga, gb]) => setSides([allFiles(ga), allFiles(gb)])).catch((e: unknown) => setError(describe(e)));
  }, [name, a, b]);

  const changes = useMemo(() => (sides ? diffManifests(sides[0], sides[1]) : []), [sides]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!sides) return <p className="muted">Loading both revisions…</p>;

  const count = (s: ManifestChange["status"]) => changes.filter((c) => c.status === s).length;

  return (
    <>
      <p className="muted" data-testid="diff-summary">
        {a === b ? "Same revision on both sides." :
          `${count("added")} added, ${count("removed")} removed, ${count("changed")} changed, ${count("unchanged")} unchanged`}
      </p>
      <table aria-label="files diff" className="compact manifest">
        <thead><tr><th>status</th><th>path</th><th>size</th></tr></thead>
        <tbody>
          {changes.map((c) => (
            <tr key={c.path} className={`status-${c.status}`} data-status={c.status} data-path={c.path}>
              <td><span className="status-tag">{c.status}</span></td>
              <td>
                <code>{c.path}</code>
                {c.status !== "removed" && <> <a className="muted" href={href({ page: "source", ref: `${name}@${b}`, path: c.path })}>view</a></>}
              </td>
              <td className="num">{sizeCell(c)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {changes.filter((c) => c.status === "changed").map((c) => <FileDiff key={c.path} change={c} />)}
    </>
  );
}

function sizeCell(c: ManifestChange): string {
  if (c.status === "added") return formatSize(c.b!.size);
  if (c.status === "removed") return formatSize(c.a!.size);
  if (c.status === "changed" && c.a!.size !== c.b!.size) return `${formatSize(c.a!.size)} → ${formatSize(c.b!.size)}`;
  return formatSize(c.b!.size);
}

const CONTEXT = 3;

function FileDiff({ change }: { change: ManifestChange }) {
  const ta = change.a!.text, tb = change.b!.text;
  const ops = useMemo(() => (ta === null || tb === null ? null : ta === tb ? [] : diffLines(ta, tb)), [ta, tb]);
  return (
    <section className="file-diff" data-testid="file-diff" data-path={change.path}>
      <h2><code>{change.path}</code></h2>
      {ops === null && <p className="muted">Files that are not text differ ({formatSize(change.a!.size)} → {formatSize(change.b!.size)}).</p>}
      {ops !== null && ops.length === 0 && <p className="muted">Contents identical; only the mode changed.</p>}
      {ops !== null && ops.length > 0 && <Hunks ops={ops} />}
    </section>
  );
}

/** The ops with long unchanged runs folded, leaving CONTEXT lines around each change. */
export function Hunks({ ops }: { ops: LineOp[] }) {
  const rows: (LineOp | { kind: "fold"; count: number })[] = [];
  let i = 0;
  while (i < ops.length) {
    if (ops[i].kind !== "equal") { rows.push(ops[i++]); continue; }
    let j = i;
    while (j < ops.length && ops[j].kind === "equal") j++;
    const run = ops.slice(i, j);
    const head = i === 0 ? 0 : CONTEXT, tail = j === ops.length ? 0 : CONTEXT;
    if (run.length > head + tail + 1) {
      rows.push(...run.slice(0, head), { kind: "fold", count: run.length - head - tail }, ...run.slice(run.length - tail));
    } else rows.push(...run);
    i = j;
  }
  return (
    <table className="line-diff" aria-label="line diff">
      <tbody>
        {rows.map((r, k) =>
          r.kind === "fold" ? (
            <tr key={k} className="fold"><td colSpan={3}>… {r.count} unchanged lines</td></tr>
          ) : (
            <tr key={k} className={`line ${r.kind}`} data-testid={`line-${r.kind}`}>
              <td className="ln">{r.a ?? ""}</td>
              <td className="ln">{r.b ?? ""}</td>
              <td className="text"><span className="sign">{r.kind === "add" ? "+" : r.kind === "remove" ? "-" : " "}</span>{r.text}</td>
            </tr>
          ),
        )}
      </tbody>
    </table>
  );
}
