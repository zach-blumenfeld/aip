import { useMemo, useRef, useState } from "react";
import { consoleRunner } from "../api/console";
import { asText, diffLines, type FileStatus } from "../diff/lines";
import { acceptResult, checkResult, type CheckName, type Verdict } from "../studio/agentCheck";
import { agentGate, type GateReason } from "../studio/agentGate";
import { contract, DEFAULT_AGENT_PROMPT, fullPrompt } from "../studio/agentPrompt";
import type { Draft } from "../studio/draft";
import { store, studioMade } from "../studio/import";
import type { Issue } from "../studio/lint";
import { buildScaffold, packScaffold } from "../studio/scaffold";
import { unpackSkill, type ZipFile } from "../zip";
import { Hunks } from "./Diff";
import { save } from "./Zip";

const CHECK_TITLES: Record<CheckName, string> = {
  validate: "aip-spec validate",
  adherence: "Adherence to the design",
  contract: "Script and template contract",
  completeness: "Completeness",
};

type Phase =
  | { at: "idle" }
  | { at: "checking"; from: string }
  | { at: "checked"; from: string; verdict: Verdict; files: ZipFile[] }
  | { at: "failed"; message: string }
  | { at: "accepted"; from: string };

interface Props {
  draft: Draft;
  files: ZipFile[];
  issues: Issue[];
  onPick: (r: GateReason) => void;
  onPrompt: (text: string | undefined) => void;
  onAccept: (d: Draft) => void;
  onClose: () => void;
}

/** "Complete with an agent", without spawning one (S6a): what the agent is asked to do, the prompt to copy, the
 *  scaffold to hand it, and the import of what it returns, which the console checks before Accept. */
export function AgentPanel({ draft, files, issues, onPick, onPrompt, onAccept, onClose }: Props) {
  const reasons = useMemo(() => agentGate(draft, issues), [draft, issues]);
  const scaffold = useMemo(() => buildScaffold(draft, files), [draft, files]);
  const [phase, setPhase] = useState<Phase>({ at: "idle" });
  const [copied, setCopied] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const blocked = reasons.length > 0;
  const filename = `${scaffold.name}.zip`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(fullPrompt(draft, scaffold.placeholders));
      setCopied("Copied the prompt.");
    } catch {
      setCopied("This browser did not allow copying; select the prompt below and copy it by hand.");
    }
  };

  const pick = async (file: File | undefined) => {
    if (input.current) input.current.value = "";
    if (!file) return;
    setPhase({ at: "checking", from: file.name });
    try {
      const { files: got } = unpackSkill(new Uint8Array(await file.arrayBuffer()));
      const verdict = await checkResult(draft, got, consoleRunner);
      setPhase({ at: "checked", from: file.name, verdict, files: got });
    } catch (e) {
      setPhase({ at: "failed", message: `Could not check ${file.name}: ${e instanceof Error ? e.message : String(e)}` });
    }
  };

  const accept = () => {
    if (phase.at !== "checked" || !phase.verdict.ok || !phase.verdict.result) return;
    const r = acceptResult(draft, phase.verdict.result, phase.files, (f) => !studioMade(f));
    onAccept({ ...r.draft, files: r.files.map(store) });
    setPhase({ at: "accepted", from: phase.from });
  };

  return (
    <section className="studio-panel studio-agent" data-testid="agent-panel" aria-label="complete with an agent">
      <h2>Complete with an agent</h2>
      {blocked ? (
        <div className="error" data-testid="agent-gate">
          <p>The agent can start once the design is complete:</p>
          <ul>
            {reasons.map((r, n) => (
              <li key={n} data-testid="agent-reason"><button className="linkish" onClick={() => onPick(r)}>{r.message}</button></li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted" data-testid="agent-ready">The design is complete; an agent can fill in the rest.</p>
      )}

      <details open data-testid="agent-info">
        <summary>What the agent does</summary>
        <ul>
          <li><strong>Asked to:</strong> replace every <code>AIP-STUDIO-PLACEHOLDER</code> file ({scaffold.placeholders.length} in this scaffold) with a working script, template, reference or asset, and fill the prose fields left empty.</li>
          <li><strong>May change:</strong> those placeholder files and empty prose fields only. Nothing in the graph, the inputs and outputs, the names, or anything already written.</li>
          <li><strong>Must run:</strong> <code>aip-spec validate</code> on its result until it passes.</li>
          <li><strong>Comes back as:</strong> a zip you import here. The console validates it, compares it to this design, runs every script with synthetic inputs, and shows it as a diff to accept or reject. A result that fails any check cannot be accepted.</li>
          <li><strong>What the checks do not prove:</strong> decisions need a decision model and client tasks need a client, so the whole procedure is not run. Scripts and templates are checked against their contracts, not for being right.</li>
        </ul>
      </details>

      <fieldset>
        <legend>Prompt</legend>
        <label className="field">
          <span>Instructions (edit for this draft; saved with it)</span>
          <textarea data-testid="agent-prompt" rows={10} value={draft.agentPrompt ?? DEFAULT_AGENT_PROMPT}
            onChange={(e) => onPrompt(e.target.value === DEFAULT_AGENT_PROMPT ? undefined : e.target.value)} />
        </label>
        {draft.agentPrompt !== undefined && <button onClick={() => onPrompt(undefined)}>reset to the default</button>}
        <details>
          <summary>The design the prompt adds (generated, not editable)</summary>
          <pre className="agent-contract" data-testid="agent-contract">{contract(draft, scaffold.placeholders)}</pre>
        </details>
      </fieldset>

      <div className="actions">
        <button data-testid="agent-copy" disabled={blocked} onClick={() => void copy()}>Copy prompt</button>
        <button data-testid="agent-download" disabled={blocked} onClick={() => save(filename, packScaffold(scaffold))}>Download {filename}</button>
        <input ref={input} type="file" accept=".zip,application/zip" aria-label="import agent result zip" hidden onChange={(e) => void pick(e.target.files?.[0])} />
        <button data-testid="agent-import" disabled={blocked || phase.at === "checking"} onClick={() => input.current?.click()}>Import the agent's result…</button>
        <button className="linkish" onClick={onClose}>close</button>
      </div>
      {copied && <p className="muted small" role="status">{copied}</p>}

      {phase.at === "checking" && <p className="muted" role="status">Checking {phase.from}…</p>}
      {phase.at === "failed" && <p className="error" role="alert" data-testid="agent-error">{phase.message}</p>}
      {phase.at === "accepted" && <p role="status" data-testid="agent-accepted">Accepted {phase.from}: its files replace the placeholders, and the prose it wrote is in the draft.</p>}
      {phase.at === "checked" && (
        <Result verdict={phase.verdict} files={phase.files} scaffold={scaffold.files} from={phase.from}
          onAccept={accept} onReject={() => setPhase({ at: "idle" })} />
      )}
    </section>
  );
}

function Result({ verdict, files, scaffold, from, onAccept, onReject }: {
  verdict: Verdict; files: ZipFile[]; scaffold: ZipFile[]; from: string; onAccept: () => void; onReject: () => void;
}) {
  return (
    <div data-testid="agent-result" data-ok={verdict.ok}>
      <h3>{from}: {verdict.ok ? "every check passed" : "not accepted"}</h3>
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
          title={verdict.ok ? undefined : "A result is accepted only when every check passes"}>Accept</button>
        <button data-testid="agent-reject" onClick={onReject}>Reject</button>
      </div>
    </div>
  );
}

/** The result against the exported scaffold: each path's status, and a line diff per changed text file. */
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
      <summary>Diff against the exported scaffold ({rows.filter((r) => r.status !== "unchanged").length} files differ)</summary>
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
