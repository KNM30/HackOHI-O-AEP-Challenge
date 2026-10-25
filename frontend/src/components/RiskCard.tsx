import type { RiskFactor, RiskResult, SeverityOption } from "../types";

const RISK_ANSWER = {
  low: "Your home is at low risk of losing power in this simulated storm.",
  moderate: "Your home is at moderate risk of losing power in this simulated storm.",
  high: "Your home is at high risk of losing power in this simulated storm.",
} as const;

// Shape + text, so the band does not rely on colour alone.
export const BAND_ICON = { low: "○", moderate: "◐", high: "●" } as const;

export const pct = (x: number) => (x < 0.01 ? "under 1%" : x > 0.99 ? "over 99%" : `${Math.round(x * 100)}%`);

/** "About 23% (90% range 8% to 50%)" for the fitted model, or null for the heuristic band. */
export function chanceText(risk: RiskResult): string | null {
  if (risk.probability === null || risk.probability_low === null || risk.probability_high === null) return null;
  return `About ${pct(risk.probability)} (90% range ${pct(risk.probability_low)} to ${pct(risk.probability_high)})`;
}

const effectText = (f: RiskFactor) =>
  f.points === null ? "" : `${f.direction === "lowers" ? "lowers" : "raises"} your chance by ${Math.abs(f.points).toFixed(1)} pts`;

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
  const fitted = risk.method === "fitted_model";
  const chance = chanceText(risk);
  const reasons = risk.factors
    .filter((f) => f.points !== null && (fitted ? f.direction !== "neutral" : f.points > 0))
    .sort((a, b) => Math.abs(b.points ?? 0) - Math.abs(a.points ?? 0))
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
      {chance && (
        <p className="chance">
          <strong>{chance}</strong> chance that storm damage cuts your supply
        </p>
      )}
      <p className="muted small">
        Model estimate for the simulated storm severity: {risk.severity_label}. Not a forecast.
        {fitted && " Validated on past storms the model had not seen."}
      </p>
      {reasons.length > 0 && (
        <>
          <h4>Main reasons</h4>
          <ul className="small tight">
            {reasons.map((f) => (
              <li key={f.name}>
                {f.name}: {f.value}
                {fitted && <span className="muted"> ({effectText(f)})</span>}
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
  const fitted = risk.method === "fitted_model";
  const card = risk.model_card;
  return (
    <>
      {fitted ? (
        <p className="small">
          {chanceText(risk)}. Each factor below shows how far it moves your chance against an average premise in the
          service area.
        </p>
      ) : (
        <p className="small">
          Heuristic score {risk.score}/100 (not a probability). {risk.score_note}
        </p>
      )}
      <h4>{fitted ? "What moves your chance" : "Points toward the score"}</h4>
      <ul className="factors">
        {risk.factors.map((f) => (
          <li key={f.name}>
            <div className="factor-head">
              <span>{f.name}</span>
              <span className="mono small">
                {f.value}
                {f.points !== null && (f.max_points ? ` - ${f.points}/${f.max_points} pts` : ` - ${effectText(f)}`)}
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
      {card && (
        <details>
          <summary>How the model was checked</summary>
          <p className="small">
            Fitted on {card.training_premises.toLocaleString()} premises on {card.training_circuits} circuits and{" "}
            {card.training_storms} past storms. {card.label_definition}
          </p>
          <ul className="small">
            {card.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <div className="table-wrap">
            <table className="jobs">
              <caption className="small">Predicted vs. observed share hit, storms held out (recalibrated)</caption>
              <thead>
                <tr>
                  <th scope="col">Predicted range</th>
                  <th scope="col">Mean predicted</th>
                  <th scope="col">Observed</th>
                  <th scope="col">Premise-storms</th>
                </tr>
              </thead>
              <tbody>
                {card.calibration.map((c) => (
                  <tr key={c.bin}>
                    <td className="mono">{c.bin.replace(/(\d\.\d+)/g, (m) => `${Math.round(Number(m) * 100)}%`)}</td>
                    <td className="mono">{(c.mean_predicted * 100).toFixed(1)}%</td>
                    <td className="mono">{(c.observed * 100).toFixed(1)}%</td>
                    <td className="mono">{c.rows.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
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
