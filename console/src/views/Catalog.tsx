import { useEffect, useState } from "react";
import { api, describe } from "../api/client";
import type { BundleRow, CatalogEntry, SearchHit } from "../api/types";
import { bundleRef, href } from "../router";
import { DraftBadge, when } from "./Record";

/** The published procedures, searchable. Drafts (bundles the server holds with no revision, from runs of a folder
 *  or a file) are not in the catalog; a toggle lists them below it. */
export function Catalog() {
  const [entries, setEntries] = useState<CatalogEntry[] | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A name whose every revision is retired no longer resolves or runs: listed last, and hidden unless asked for.
  const [showRetired, setShowRetired] = useState(false);
  const [showDrafts, setShowDrafts] = useState(false);
  const [drafts, setDrafts] = useState<BundleRow[] | null>(null);

  const fail = (e: unknown) => setError(describe(e));

  useEffect(() => { api.catalog().then(setEntries).catch(fail); }, []);
  useEffect(() => {
    if (showDrafts && drafts === null) api.bundles(true).then(setDrafts).catch(fail);
  }, [showDrafts, drafts]);

  // Search replaces the table while the query is non-empty; debounced so typing does not fire a request per keystroke.
  useEffect(() => {
    const q = query.trim();
    if (!q) { setHits(null); return; }
    const t = setTimeout(() => api.search(q).then(setHits).catch(fail), 200);
    return () => clearTimeout(t);
  }, [query]);

  const link = (name: string, revision?: string) => href({ page: "procedure", ref: revision ? `${name}@${revision}` : name });
  const retired = (entries ?? []).filter((e) => e.resolves === null);
  const live = (entries ?? []).filter((e) => e.resolves !== null);
  const listed = showRetired ? [...live, ...retired] : live;

  return (
    <>
      <form role="search" onSubmit={(e) => e.preventDefault()}>
        <input type="search" placeholder="Search procedures by what they do…" aria-label="search" value={query}
               onChange={(e) => setQuery(e.target.value)} autoFocus />
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {hits !== null ? (
        hits.length === 0 ? <p className="muted">No procedure matches “{query.trim()}”.</p> : (
          <table aria-label="search results">
            <thead><tr><th>#</th><th>Name</th><th>Description</th><th>Revision</th><th>Score</th></tr></thead>
            <tbody>
              {hits.map((h, i) => (
                <tr key={`${h.name}@${h.revision}`}>
                  <td className="muted">{i + 1}</td>
                  <td><a href={link(h.name, h.revision)}><code>{h.name}</code></a></td>
                  <td>{h.description}</td>
                  <td><code>{h.revision}</code></td>
                  <td>{h.score.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : entries === null ? <p className="muted">Loading catalog…</p> : (
        <>
          <p className="muted small catalog-retired">
            {retired.length > 0 && (
              <label>
                <input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} />
                {" "}show {retired.length} {retired.length === 1 ? "name" : "names"} with every revision retired{" "}
              </label>
            )}
            <label>
              <input type="checkbox" checked={showDrafts} data-testid="show-drafts" onChange={(e) => setShowDrafts(e.target.checked)} />
              {" "}show drafts
            </label>
          </p>
          {entries.length === 0 ? <p className="muted" data-testid="empty-catalog">Nothing is published. <code>aip publish FOLDER</code> publishes a procedure.</p> : (
            <table aria-label="catalog">
              <thead><tr><th>Name</th><th>Description</th><th>Runs as</th><th>Revisions</th></tr></thead>
              <tbody>
                {listed.map((e) => (
                  <tr key={e.name} data-testid="catalog-row" data-name={e.name} data-retired={e.resolves === null ? "true" : undefined}>
                    <td><a href={link(e.name)}><code>{e.name}</code></a></td>
                    <td>{e.description}</td>
                    <td>{e.resolves === null ? <span className="muted" data-testid="all-retired">all retired</span>
                                             : <><code>@{e.resolves}</code>{e.pinned ? " (pinned)" : ""}</>}</td>
                    <td>{e.revisions.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {showDrafts && (
            <section data-testid="drafts">
              <h2>Drafts</h2>
              <p className="muted small">
                Bundles the server holds with no revision: a run of a folder or an <code>.rl</code> file was recorded against each.
                No name resolves to one; <code>aip publish</code> gives it a revision.
              </p>
              {drafts === null ? <p className="muted">Loading drafts…</p> : drafts.length === 0 ? <p className="muted" data-testid="no-drafts">No drafts.</p> : (
                <table aria-label="drafts">
                  <thead><tr><th>Name</th><th>Description</th><th>Bundle</th><th>Stored</th><th></th></tr></thead>
                  <tbody>
                    {drafts.map((d) => (
                      <tr key={d.bundle_id} data-testid="draft-row" data-name={d.name}>
                        <td><a href={href({ page: "procedure", ref: bundleRef(d.bundle_id) })}><code>{d.name}</code></a> <DraftBadge draft /></td>
                        <td>{d.description}</td>
                        <td><code title={d.bundle_id}>{d.bundle_id.slice(0, 12)}</code></td>
                        <td className="when">{when(d.stored_at)}</td>
                        <td><a href={href({ page: "runs", name: d.name, draft: true })}>runs</a></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}
        </>
      )}
    </>
  );
}
