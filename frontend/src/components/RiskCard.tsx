import type { RiskResult, SeverityOption } from "../types";

const RISK_ANSWER = {
  low: "Your home is at low risk of losing power in this simulated storm.",
  moderate: "Your home is at moderate risk of losing power in this simulated storm.",
  high: "Your home is at high risk of losing power in this simulated storm.",
} as const;

// Shape + text, so the band does not rely on colour alone.
export const BAND_ICON = { low: "○", moderate: "◐", high: "●" } as const;

export function SeverityControl({
  severity,
  options,
  onSeverity,
}: {
  severity: string;
  options: SeverityOption[];
  onSeverity: (id: string) => void;
}) {
  const current = options.find((o) => o.id === severity);
  return (
    <label className="field">
      <span>
        Simulated storm severity <span className="muted">(scenario input, not a forecast)</span>
      </span>
      <select value={severity} onChange={(e) => onSeverity(e.target.value)} disabled={!options.length}>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
      {current && <span className="muted small">{current.description}</span>}
    </label>
  );
}

/** Band, a separate confidence label and the main contributing reasons. */
export function RiskSummary({ risk, loading }: { risk: RiskResult | null; loading: boolean }) {
  if (!risk) return <p className="muted small">{loading ? "Calculating..." : "Choose your home first."}</p>;
  if (risk.status === "insufficient_data" || !risk.band || !risk.confidence) {
    return (
      <div className="fallback" aria-busy={loading}>
        <p className="pending-badge">Insufficient information</p>
        <p>{risk.fallback_message}</p>
        <ul className="small">
          {risk.missing_inputs.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      </div>
    );
  }
  const reasons = risk.factors
    .filter((f) => f.points !== null && f.points > 0)
    .sort((a, b) => (b.points ?? 0) - (a.points ?? 0))
    .slice(0, 3);
  return (
    <div className={loading ? "stale" : undefined} aria-busy={loading}>
      <div className="band-row">
        <span className={`band band-${risk.band}`}>
          <span aria-hidden>{BAND_ICON[risk.band]}</span> {risk.band} risk
        </span>
        <span className="conf">Confidence: {risk.confidence.level}</span>
      </div>
      <p className="answer-line">{RISK_ANSWER[risk.band]}</p>
      <p className="muted small">Model estimate for the simulated storm severity: {risk.severity_label}. Not a forecast.</p>
      {reasons.length > 0 && (
        <>
          <h4>Main reasons</h4>
          <ul className="small tight">
            {reasons.map((f) => (
              <li key={f.name}>
                {f.name}: {f.value}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** Full factor breakdown and model detail, shown behind an expander. */
export function RiskDetails({ risk }: { risk: RiskResult | null }) {
  if (!risk || risk.status !== "calculated" || !risk.confidence) {
    return <p className="muted small">No risk explanation is available for this premise.</p>;
  }
  return (
    <>
      <p className="small">
        Heuristic score {risk.score}/100 (not a probability). {risk.score_note}
      </p>
      <h4>Points toward the score</h4>
      <ul className="factors">
        {risk.factors.map((f) => (
          <li key={f.name}>
            <div className="factor-head">
              <span>{f.name}</span>
              <span className="mono small">
                {f.value}
                {f.points !== null && ` - ${f.points}/${f.max_points} pts`}
              </span>
            </div>
            {f.points !== null && f.max_points ? (
              <div className="meter" aria-hidden>
                <span style={{ width: `${(100 * f.points) / f.max_points}%` }} />
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <details>
        <summary>What each factor means</summary>
        <ul className="small">
          {risk.factors.map((f) => (
            <li key={f.name}>
              <strong>{f.name}:</strong> {f.explanation}
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Confidence details ({risk.confidence.points}/100 after deductions)</summary>
        <ul className="small">
          {risk.confidence.reasons.map((r) => (
            <li key={r.text}>
              {r.effect} - {r.text}
            </li>
          ))}
        </ul>
        <p className="muted small">{risk.confidence.ceiling_note}</p>
      </details>
      <details>
        <summary>What could change this</summary>
        <ul className="small">
          {risk.could_change.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Assumptions and missing inputs</summary>
        <ul className="small">
          {[...risk.assumptions, ...risk.missing_inputs].map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
    </>
  );
}
