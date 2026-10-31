import { useEffect, useMemo, useRef, useState } from "react";
import { consoleRunner, readHandoff, writeHandoff } from "../api/console";
import { asText, diffLines, type FileStatus } from "../diff/lines";
import { acceptResult, checkResult, type CheckName, type Verdict } from "../studio/agentCheck";
import { agentGate, type GateReason } from "../studio/agentGate";
import { DEFAULT_AGENT_PROMPT, fullPrompt } from "../studio/agentPrompt";
import type { Draft } from "../studio/draft";
import { store, studioMade } from "../studio/import";
import { PLACEHOLDER_MARKER, type Issue } from "../studio/lint";
import { buildScaffold } from "../studio/scaffold";
import type { ZipFile } from "../zip";
import { Hunks } from "./Diff";

const CHECK_TITLES: Record<CheckName, string> = {
  validate: "aip-spec validate",
  adherence: "Adherence to the design",
  contract: "Script and template contract",
  completeness: "Completeness",
};
/** How often the folder is read; a change is checked once two reads in a row agree, so the agent is done writing. */
const POLL_MS = 1000;

type Watch =
  | { at: "waiting"; replaced: number }
  | { at: "checking" }
  | { at: "checked"; verdict: Verdict; files: ZipFile[]; run: number }
  | { at: "gone" }
  | { at: "error"; message: string };

interface Props {
  draft: Draft;
  files: ZipFile[];
  issues: Issue[];
  onPick: (r: GateReason) => void;
  /** A change to the draft that is not a design edit: the prompt, or the handoff. */
  onChange: (change: (d: Draft) => void) => void;
  onAccept: (d: Draft) => void;
  onClose: () => void;
}

/** "Complete with an agent": the scaffold is written to a folder, the user pastes one prompt into their coding agent,
 *  and the Studio watches the folder, checking the agent's work each time it settles. Accept takes it into the draft. */
export function AgentPanel({ draft, files, issues, onPick, onChange, onAccept, onClose }: Props) {
  const reasons = useMemo(() => agentGate(draft, issues), [draft, issues]);
  const scaffold = useMemo(() => buildScaffold(draft, files), [draft, files]);
  const handoff = draft.handoff;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  const blocked = reasons.length > 0;
  const prompt = handoff ? fullPrompt(draft, scaffold.placeholders, handoff.dir) : "";

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const { dir } = await writeHandoff(scaffold.name, scaffold.files);
      const { hash } = await readHandoff(scaffold.name);
      onChange((d) => { d.handoff = { name: scaffold.name, dir, baseline: hash }; });
      setAccepted(false);
    } catch (e) {
      setError(`Could not write the folder: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied("Copied. Paste it into your coding agent.");
    } catch {
      setCopied("This browser did not allow copying; select the prompt and copy it by hand.");
    }
  };

  const watch = useWatch(handoff && !accepted ? handoff : null, draft, scaffold.placeholders.map((p) => p.path));

  const accept = () => {
    if (watch.at !== "checked" || !watch.verdict.ok || !watch.verdict.result) return;
    const r = acceptResult(draft, watch.verdict.result, watch.files, (f) => !studioMade(f));
    onAccept({ ...r.draft, files: r.files.map(store) });
    setAccepted(true);
  };

  return (
    <section className="studio-panel studio-agent" data-testid="agent-panel" aria-label="complete with an agent">
      <h2>Complete with an agent</h2>
      {blocked && (
        <div className="error" data-testid="agent-gate">
          <p>The agent can start once the design is complete:</p>
          <ul>
            {reasons.map((r, n) => (
              <li key={n} data-testid="agent-reason"><button className="linkish" onClick={() => onPick(r)}>{r.message}</button></li>
            ))}
          </ul>
        </div>
      )}

      {!handoff && (
        <>
          <p className="muted">
            The Studio writes the scaffold to a folder on this machine and gives you one prompt. Paste it into your
            coding agent; the Studio watches the folder and checks the agent's work as it lands.
          </p>
          <div className="actions">
            <button data-testid="agent-start" disabled={blocked || busy} onClick={() => void start()}>{busy ? "writing…" : "Start"}</button>
            <button className="linkish" onClick={onClose}>close</button>
          </div>
        </>
      )}

      {handoff && (
        <>
          <p>Paste this into your coding agent. It edits <code data-testid="agent-dir">{handoff.dir}</code> in place.</p>
          <textarea className="agent-prompt" data-testid="agent-prompt-text" readOnly rows={8} value={prompt} onFocus={(e) => e.target.select()} />
          <div className="actions">
            <button data-testid="agent-copy" onClick={() => void copy()}>Copy prompt</button>
            <button data-testid="agent-restart" disabled={blocked || busy} onClick={() => void start()}
              title="Writes a fresh scaffold; the folder as it is now is moved to studio/.previous/">start over</button>
            <button className="linkish" onClick={onClose}>close</button>
          </div>
          {copied && <p className="muted small" role="status">{copied}</p>}
        </>
      )}

      <details>
        <summary>Edit the instructions</summary>
        <p className="muted small">Saved with this draft. The folder and the design are added after them and cannot be edited out.</p>
        <textarea className="agent-prompt" data-testid="agent-prompt" rows={10} value={draft.agentPrompt ?? DEFAULT_AGENT_PROMPT}
          onChange={(e) => { const v = e.target.value; onChange((d) => { if (v === DEFAULT_AGENT_PROMPT) delete d.agentPrompt; else d.agentPrompt = v; }); }} />
        {draft.agentPrompt !== undefined && <button onClick={() => onChange((d) => { delete d.agentPrompt; })}>reset to the default</button>}
      </details>

      {error && <p className="error" role="alert" data-testid="agent-error">{error}</p>}
      {accepted && <p role="status" data-testid="agent-accepted">Accepted: the agent's files replace the placeholders, and the prose it wrote is in the draft.</p>}
      {handoff && !accepted && (
        <>
          {watch.at === "waiting" && (
            <p className="muted" role="status" data-testid="agent-waiting">
              Waiting for the agent: {watch.replaced} of {scaffold.placeholders.length} placeholder files written.
            </p>
          )}
          {watch.at === "checking" && <p className="muted" role="status">The folder changed; checking…</p>}
          {watch.at === "gone" && <p className="error" role="alert">The folder is gone. Start over to write it again.</p>}
          {watch.at === "error" && <p className="error" role="alert">{watch.message}</p>}
          {watch.at === "checked" && <Result verdict={watch.verdict} files={watch.files} scaffold={scaffold.files} run={watch.run} onAccept={accept} />}
        </>
      )}
      <p className="muted small">
        The checks do not run the whole procedure (decisions need a decision model, client tasks a client), and they do
        not judge whether a script does the right thing: read the diff for that.
      </p>
    </section>
  );
}

/** Read the folder every second; once it has changed from the scaffold and two reads agree, run the checks. */
function useWatch(handoff: Draft["handoff"] | null, draft: Draft, placeholders: string[]): Watch {
  const [watch, setWatch] = useState<Watch>({ at: "waiting", replaced: 0 });
  const latest = useRef({ draft, placeholders });
  latest.current = { draft, placeholders };
  useEffect(() => {
    if (!handoff) return;
    let stopped = false, last: string | null = null, checked: string | null = null, run = 0, timer = 0;
    setWatch({ at: "waiting", replaced: 0 });
    const tick = async () => {
      try {
        const now = await readHandoff(handoff.name);
        if (stopped) return;
        if (now.missing) { setWatch({ at: "gone" }); return schedule(); }
        const stable = now.hash === last;
        last = now.hash;
        if (now.hash === handoff.baseline || now.hash === checked) {
          if (now.hash === handoff.baseline) setWatch({ at: "waiting", replaced: replaced(now.files, latest.current.placeholders) });
          return schedule();
        }
        if (!stable) return schedule();
        checked = now.hash;
        setWatch({ at: "checking" });
        const verdict = await checkResult(latest.current.draft, now.files, consoleRunner);
        if (!stopped) setWatch({ at: "checked", verdict, files: now.files, run: ++run });
      } catch (e) {
        if (!stopped) setWatch({ at: "error", message: `Could not read the folder: ${e instanceof Error ? e.message : String(e)}` });
      }
      schedule();
    };
    const schedule = () => { if (!stopped) timer = window.setTimeout(() => void tick(), POLL_MS); };
    void tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, [handoff?.dir, handoff?.baseline]);
  return watch;
}

function replaced(files: ZipFile[], placeholders: string[]): number {
  const decoder = new TextDecoder();
  return placeholders.filter((p) => {
    const f = files.find((x) => x.path === p);
    return f && !decoder.decode(f.bytes).includes(PLACEHOLDER_MARKER);
  }).length;
}

function Result({ verdict, files, scaffold, run, onAccept }: {
  verdict: Verdict; files: ZipFile[]; scaffold: ZipFile[]; run: number; onAccept: () => void;
}) {
  return (
    <div data-testid="agent-result" data-ok={verdict.ok} data-run={run}>
      <h3>{verdict.ok ? "Every check passed" : "Not ready yet"} <span className="muted small">(check {run})</span></h3>
      {!verdict.ok && !verdict.refused && <p className="muted small">The Studio checks again when the folder changes. Paste the failures into your agent to have them fixed.</p>}
      {verdict.refused && <p className="error" role="alert" data-testid="agent-refused">The checks did not run: {verdict.refused}</p>}
      {verdict.checks.length > 0 && (
        <ul className="agent-checks" data-testid="agent-checks">
          {verdict.checks.map((c) => (
            <li key={c.name} data-check={c.name} data-ok={c.ok}>
              <strong className={c.ok ? undefined : "error"}>{c.ok ? "pass" : "fail"}</strong> {CHECK_TITLES[c.name]}
              {c.failures.length > 0 && <ul>{c.failures.map((f, n) => <li key={n} data-testid="agent-failure">{f}</li>)}</ul>}
            </li>
          ))}
        </ul>
      )}
      {verdict.filled.length > 0 && (
        <details open data-testid="agent-filled">
          <summary>Prose the agent wrote ({verdict.filled.length})</summary>
          <ul>{verdict.filled.map((f, n) => <li key={n}><strong>{f.label}:</strong> {f.value}</li>)}</ul>
        </details>
      )}
      {verdict.flags.length > 0 && (
        <div className="published-note" data-testid="agent-flags">
          <p>Look at these before accepting:</p>
          <ul>{verdict.flags.map((f, n) => <li key={n}>{f}</li>)}</ul>
        </div>
      )}
      <FilesDiff scaffold={scaffold} result={files} />
      <div className="actions">
        <button data-testid="agent-accept" disabled={!verdict.ok} onClick={onAccept}
          title={verdict.ok ? undefined : "Accept needs every check to pass"}>Accept</button>
      </div>
    </div>
  );
}

/** The folder against the scaffold as written: each path's status, and a line diff per changed text file. */
function FilesDiff({ scaffold, result }: { scaffold: ZipFile[]; result: ZipFile[] }) {
  const rows = useMemo(() => {
    const a = new Map(scaffold.map((f) => [f.path, f])), b = new Map(result.map((f) => [f.path, f]));
    return [...new Set([...a.keys(), ...b.keys()])].sort().map((path) => {
      const fa = a.get(path), fb = b.get(path);
      const same = fa && fb && fa.mode === fb.mode && fa.bytes.length === fb.bytes.length && fa.bytes.every((x, i) => x === fb.bytes[i]);
      const status: FileStatus = !fa ? "added" : !fb ? "removed" : same ? "unchanged" : "changed";
      const ta = fa ? asText(fa.bytes) : "", tb = fb ? asText(fb.bytes) : "";
      const ops = status !== "unchanged" && ta !== null && tb !== null ? diffLines(ta ?? "", tb ?? "") : null;
      return { path, status, ops };
    });
  }, [scaffold, result]);
  return (
    <details data-testid="agent-diff">
      <summary>Diff against the scaffold ({rows.filter((r) => r.status !== "unchanged").length} files differ)</summary>
      <table className="compact manifest" aria-label="files diff">
        <tbody>
          {rows.map((r) => (
            <tr key={r.path} className={`status-${r.status}`} data-status={r.status} data-path={r.path}>
              <td><span className="status-tag">{r.status}</span></td>
              <td><code>{r.path}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.filter((r) => r.ops && r.ops.some((o) => o.kind !== "equal")).map((r) => (
        <section key={r.path} className="file-diff" data-path={r.path}>
          <h4><code>{r.path}</code></h4>
          <Hunks ops={r.ops!} />
        </section>
      ))}
    </details>
  );
}
