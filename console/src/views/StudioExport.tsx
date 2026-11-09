import { useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { isFolderMode } from "../api/console";
import type { ValidationIssue } from "../api/types";
import { navigate } from "../router";
import type { Draft } from "../studio/draft";
import { buildScaffold, packScaffold } from "../studio/scaffold";
import type { ZipFile } from "../zip";
import { describe } from "./Source";
import { Issues, save, stashPublished } from "./Zip";

type Phase =
  | { at: "idle" }
  | { at: "busy" }
  | { at: "failed"; message: string; issues: ValidationIssue[]; forbidden: boolean };

/** The export: the linter's verdict on what the zip will hold, then a download (never blocked) and, with a server
 *  behind the console, a publish to the catalog, which the server refuses while errors remain, so the button
 *  says why instead. */
export function ExportPanel({ draft, files, onClose }: { draft: Draft; files: ZipFile[]; onClose: () => void }) {
  const scaffold = useMemo(() => buildScaffold(draft, files), [draft, files]);
  const [phase, setPhase] = useState<Phase>({ at: "idle" });
  const count = (tier: string) => scaffold.issues.filter((i) => i.tier === tier).length;
  const errors = count("error");
  const filename = `${scaffold.name}.zip`;

  const publish = async () => {
    setPhase({ at: "busy" });
    try {
      const before = await api.catalog().then((all) => all.find((c) => c.name === scaffold.name)?.revisions.map((r) => r.revision) ?? [], () => [] as string[]);
      const result = await api.publish(scaffold.files);
      const ref = `${result.name}@${result.revision}`;
      stashPublished(ref, { existed: before.includes(result.revision), warnings: result.warnings, from: filename });
      navigate({ page: "procedure", ref });
    } catch (e) {
      const forbidden = e instanceof ApiError && (e.status === 401 || e.status === 403);
      setPhase({ at: "failed", message: describe(e), issues: e instanceof ApiError ? e.issues : [], forbidden });
    }
  };

  return (
    <section className="studio-panel studio-export" data-testid="export-panel" aria-label="export">
      <h2>Export the scaffold</h2>
      <p data-testid="export-summary" data-errors={errors} data-unfinished={count("unfinished")} data-warnings={count("warning")}>
        <span className={errors ? "error" : undefined}>{errors} error{errors === 1 ? "" : "s"}</span>,
        {" "}{count("unfinished")} unfinished, {count("warning")} warning{count("warning") === 1 ? "" : "s"}.
        {errors > 0 && " The zip is marked as a draft in source/README.md, and aip-spec will reject it until the errors are fixed."}
      </p>
      <details>
        <summary>{scaffold.files.length} files, {scaffold.placeholders.length} of them placeholders</summary>
        <ul className="export-files" data-testid="export-files">
          {scaffold.files.map((f) => (
            <li key={f.path}><code>{f.path}</code>{scaffold.placeholders.some((p) => p.path === f.path) && <span className="muted"> (placeholder)</span>}</li>
          ))}
        </ul>
      </details>
      <div className="actions">
        <button type="button" data-testid="export-download" onClick={() => save(filename, packScaffold(scaffold))}>Download {filename}</button>
        {!isFolderMode() && (
          <button type="button" data-testid="export-publish" disabled={errors > 0 || phase.at === "busy"} onClick={() => void publish()}
            title={errors > 0 ? "The server rejects a skill with errors" : undefined}>
            {phase.at === "busy" ? "publishing…" : "Publish to catalog"}
          </button>
        )}
        <button type="button" className="linkish" onClick={onClose}>close</button>
      </div>
      {!isFolderMode() && errors > 0 && (
        <p className="muted small" data-testid="export-publish-reason">Publishing needs the errors fixed first: the server rejects a skill that fails validation.</p>
      )}
      {phase.at === "failed" && (
        <div className="error" role="alert" data-testid="export-error">
          <p>Not published: {phase.message}{phase.forbidden ? ". Set a token with the publish scope on the Server page." : ""}</p>
          {phase.issues.length > 0 && <Issues issues={phase.issues} />}
        </div>
      )}
    </section>
  );
}
