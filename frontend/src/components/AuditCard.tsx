import { useCallback, useEffect, useState } from "react";
import { api, isAbort } from "../api";
import type { AuditEntry } from "../types";

const WHAT: Record<AuditEntry["endpoint"], string> = {
  risk: "Pre-storm risk",
  simulation: "Restoration scenario",
  briefing: "Guidance and alerts",
  assistant: "Assistant answer",
};

const kv = (o: AuditEntry["inputs"]) =>
  Object.entries(o)
    .filter(([, v]) => v !== null && v !== "")
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
    .join("; ");

/** This session's server-side audit trail: which model answered, from which inputs, with what result. */
export function AuditCard({ active }: { active: boolean }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    api
      .audit(signal)
      .then((e) => {
        setEntries(e);
        setError(null);
      })
      .catch((e) => {
        if (!isAbort(e)) setError(String(e));
      });
  }, []);

  useEffect(() => {
    if (!active) return;
    const c = new AbortController();
    load(c.signal);
    return () => c.abort();
  }, [active, load]);

  return (
    <section className="card" aria-labelledby="audit-h">
      <h2 id="audit-h">Audit trail</h2>
      <p className="muted small">
        Every answer this session received, recorded by the server: hashed premise IDs, the inputs, a summary of the
        result and the model build. Questions you type are never stored, only their length and topic. The trail is
        kept in memory and cleared when the server restarts.{" "}
        <button type="button" className="link-btn" onClick={() => load()}>
          Refresh
        </button>
      </p>
      {error && (
        <p className="error small" role="alert">
          The audit trail is unavailable ({error}).
        </p>
      )}
      {entries && entries.length === 0 && <p className="small">Nothing recorded yet. Choose a home to start.</p>}
      {entries && entries.length > 0 && (
        <div className="table-wrap">
          <table className="jobs">
            <thead>
              <tr>
                <th scope="col">Time (UTC)</th>
                <th scope="col">Decision</th>
                <th scope="col">Inputs</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {[...entries].reverse().map((e) => (
                <tr key={e.seq}>
                  <td className="mono small">{e.at.slice(11, 19)}</td>
                  <td className="small">
                    {WHAT[e.endpoint]}
                    {e.premise_id && <div className="mono muted">{e.premise_id}</div>}
                  </td>
                  <td className="small">{kv(e.inputs)}</td>
                  <td className="small">{kv(e.outputs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {entries && entries.length > 0 && <p className="muted small">Model build: {entries[entries.length - 1].model}</p>}
    </section>
  );
}
