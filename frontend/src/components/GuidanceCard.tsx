import type { BriefingResponse, Recommendation } from "../types";

function Item({ g }: { g: Recommendation }) {
  return (
    <li className={`rec rec-${g.category}`}>
      <div className="rec-head">
        <span className={`urg urg-${g.urgency.replace(/ /g, "-")}`}>{g.urgency}</span>
        <strong>{g.action}</strong>
      </div>
      {g.note && <p className="small note">{g.note}</p>}
      <details className="rec-more">
        <summary className="small">Why and source</summary>
        <p className="small muted">Why: {g.why}</p>
        <p className="small muted">
        {g.sources.length > 0 ? (
          <>
            Source:{" "}
            {g.sources.map((s, i) => (
              <span key={s.id}>
                {i > 0 && "; "}
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.title}
                </a>
              </span>
            ))}{" "}
            (checked {g.sources[0].verified_on})
          </>
        ) : (
          g.source_note
        )}
        </p>
      </details>
    </li>
  );
}

const TOP_ACTIONS = 3;

/**
 * Overview: urgent safety guidance (always shown when present) and the top preparation steps.
 * The backend already orders guidance by category and urgency.
 */
export function TopActions({ briefing, loading, error }: { briefing: BriefingResponse | null; loading: boolean; error: string | null }) {
  if (error) return <p className="error small">Guidance is unavailable right now ({error}).</p>;
  if (!briefing) return <p className="muted small">{loading ? "Loading..." : "Choose your home first."}</p>;
  const emergency = briefing.guidance.filter((g) => g.category === "emergency");
  const routine = briefing.guidance.filter((g) => g.category === "routine").slice(0, TOP_ACTIONS);
  return (
    <div className={loading ? "stale" : undefined} aria-busy={loading}>
      {emergency.length > 0 && (
        <div className="safety" role="note" aria-label="Emergency and safety">
          <h4 className="emergency-title">Emergency and safety</h4>
          <ul className="recs">
            {emergency.map((g) => (
              <Item key={g.id} g={g} />
            ))}
          </ul>
        </div>
      )}
      {routine.length ? (
        <ol className="recs">
          {routine.map((g) => (
            <Item key={g.id} g={g} />
          ))}
        </ol>
      ) : (
        <p className="muted small">No specific preparation steps for this situation.</p>
      )}
    </div>
  );
}

export function GuidanceCard({ briefing, loading, error }: { briefing: BriefingResponse | null; loading: boolean; error: string | null }) {
  const emergency = briefing?.guidance.filter((g) => g.category === "emergency") ?? [];
  const routine = briefing?.guidance.filter((g) => g.category === "routine") ?? [];
  return (
    <div aria-busy={loading}>
      {error && <p className="error small">Guidance is unavailable right now ({error}).</p>}
      {!briefing && !error && <p className="muted small">{loading ? "Loading..." : "Choose your home first."}</p>}
      {briefing && (
        <div className={loading ? "stale" : undefined}>
          {emergency.length > 0 && (
            <>
              <h4 className="emergency-title">Emergency and safety</h4>
              <ul className="recs">
                {emergency.map((g) => (
                  <Item key={g.id} g={g} />
                ))}
              </ul>
            </>
          )}
          <h4>Preparation</h4>
          {routine.length ? (
            <ul className="recs">
              {routine.map((g) => (
                <Item key={g.id} g={g} />
              ))}
            </ul>
          ) : (
            <p className="muted small">No specific preparation steps for this situation.</p>
          )}
          <p className="muted small">{briefing.guidance_note}</p>
        </div>
      )}
    </div>
  );
}
