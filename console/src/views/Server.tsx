import { useState } from "react";
import { api, serverUrl, setToken, token } from "../api/client";
import { consoleConfig } from "../api/console";
import { describe } from "./Source";

/** The server this console was started for, and the bearer token this browser sends it (design §11: the
 *  token never outlives the session, so it lives in sessionStorage). The server itself is fixed by
 *  `aip-console --server URL` (or `aip config`), since the runs the console starts use it too. */
export function Server() {
  const [bearer, setBearer] = useState(token());
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const config = consoleConfig();

  const save = async () => {
    setError(null);
    setNote(null);
    setToken(bearer || null);
    try {
      const all = await api.catalog();
      setNote(`Saved. The catalog at ${serverUrl()} has ${all.length} ${all.length === 1 ? "procedure" : "procedures"}.`);
    } catch (e) {
      setError(describe(e));
    }
  };

  return (
    <article className="server">
      <h1>Server</h1>
      <dl>
        <dt>server</dt><dd><code data-testid="server-url">{config.server}</code> <span className="muted small">from <code>aip-console --server</code>, else <code>aip config</code>; the page calls it directly</span></dd>
        <dt>runs</dt><dd>by <code>aip {config.aip.version}</code> (format {config.aip.format}) on this machine, in <code>{config.workdir}</code></dd>
      </dl>
      <form onSubmit={(e) => { e.preventDefault(); void save(); }} className="fields">
        <label className="field">bearer token
          <input type="password" aria-label="bearer token" value={bearer} autoComplete="off"
                 onChange={(e) => setBearer(e.target.value)} />
          <span className="muted small">
            What this page sends: needed off localhost, and for pin and retire (the <code>publish</code> scope). Kept for this
            tab's session only. Runs use the CLI's own token (<code>aip config --token</code>).
          </span>
        </label>
        <div className="actions">
          <button type="submit">Save</button>
          <button type="button" onClick={() => { setBearer(""); setToken(null); setNote("Cleared."); }}>Clear</button>
        </div>
      </form>
      {note && <p className="muted" data-testid="server-note">{note}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </article>
  );
}
