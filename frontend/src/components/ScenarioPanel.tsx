import type { Dispatch } from "react";
import type { ScenarioAction, ScenarioState } from "../scenarioState";
import type { ImpactStatus, ScenarioOption, ScenarioResult } from "../types";

interface Props {
  options: ScenarioOption[];
  state: ScenarioState;
  dispatch: Dispatch<ScenarioAction>;
  disabled: boolean;
}

export const STATUS_TEXT: Record<ImpactStatus, string> = {
  not_interrupted: "Power stays on",
  repair_dependent: "Power back after the repair",
  isolation_candidate: "May come back sooner (power rerouted)",
  unresolved: "Unclear if power comes back sooner",
};

/** What the simulated damage means for the selected home, in plain language. */
export const IMPACT_TEXT: Record<ImpactStatus, string> = {
  not_interrupted: "Your power stays on in this simulation.",
  repair_dependent: "Your power goes out in this simulation and comes back after the repair.",
  isolation_candidate:
    "Your power goes out in this simulation, but may come back sooner if crews can reroute power around the damage.",
  unresolved: "Your power goes out in this simulation. It is unclear whether crews can restore it before the repair.",
};

const MAX_LISTED = 8;

function Chooser({ options, state, dispatch, disabled }: Props) {
  const current = options.find((o) => o.id === state.draft.scenarioId) ?? null;
  const active = state.active;
  return (
    <>
      <label className="field">
        <span>Damage scenario</span>
        <select
          id="scenario-select"
          value={state.draft.scenarioId ?? ""}
          disabled={disabled}
          onChange={(e) => {
            const opt = options.find((o) => o.id === e.target.value);
            if (opt) dispatch({ type: "choose", scenario: opt });
          }}
        >
          <option value="">{active ? "-" : "No scenario (pre-storm view)"}</option>
          {options.map((o) => (
            <option key={o.id} value={o.id} disabled={!o.available}>
              {o.label}
              {o.available ? "" : " (not available)"}
            </option>
          ))}
        </select>
      </label>
      {current && <p className="muted small">{current.description}</p>}

      {current && current.locations.length > 0 && (
        <fieldset className="locations">
          <legend className="small">
            {current.mode === "single" ? "Damage location" : `Damage locations (${state.draft.locationIds.length} selected)`}
          </legend>
          {current.locations.slice(0, MAX_LISTED).map((l) => (
            <label key={l.id} className="small loc-option">
              <input
                type={current.mode === "single" ? "radio" : "checkbox"}
                name="scenario-location"
                checked={state.draft.locationIds.includes(l.id)}
                onChange={() =>
                  dispatch(current.mode === "single" ? { type: "setLocation", id: l.id } : { type: "toggleLocation", id: l.id })
                }
              />
              {l.label}
            </label>
          ))}
          {current.locations.length > MAX_LISTED && (
            <p className="muted small">
              + {current.locations.length - MAX_LISTED} more locations included ({state.draft.locationIds.length} selected in
              total).
            </p>
          )}
        </fieldset>
      )}

      <div className="row">
        <button
          type="button"
          onClick={() => current && dispatch({ type: "activate", label: current.label })}
          disabled={!current || !state.draft.locationIds.length || state.status === "loading"}
        >
          {state.status === "loading" ? "Simulating..." : "Simulate damage"}
        </button>
        <button type="button" className="secondary" onClick={() => dispatch({ type: "reset" })} disabled={!active && !current}>
          Reset
        </button>
      </div>
    </>
  );
}

/** Damage scenario selection and the Simulate action. */
export function ScenarioPanel(props: Props) {
  const active = props.state.active;
  return (
    <div>
      {active ? (
        <>
          <p className="active-scenario small">
            <strong>Simulated damage:</strong> {active.label} ({active.locationIds.length} damage location
            {active.locationIds.length === 1 ? "" : "s"}). This damage stays the same if you look at other homes.
          </p>
          <details>
            <summary>Try a different damage scenario</summary>
            <Chooser {...props} />
          </details>
        </>
      ) : (
        <>
          <p className="muted small">Pick a what-if damage scenario near your home. Nothing here is a real outage.</p>
          <Chooser {...props} />
        </>
      )}
      {props.state.error && (
        <p className="error small" role="alert">
          {props.state.error}
        </p>
      )}
    </div>
  );
}

/** How the premise and the whole circuit are affected by the active scenario (collapsed). */
export function ScenarioImpact({ r, stale }: { r: ScenarioResult; stale: boolean }) {
  return (
    <details className={`scenario-result ${stale ? "stale" : ""}`}>
      <summary>
        Your line: {r.initially_interrupted} of {r.circuit_premises} homes and businesses lose power, {r.repair_dependent} wait for the
        repair
      </summary>
      <ul className="small">
        {r.selected_premise.reasons.slice(0, 6).map((x, i) => (
          <li key={`${x.location_id}-${i}`}>{x.text}</li>
        ))}
        {r.selected_premise.reasons.length > 6 && (
          <li className="muted">+ {r.selected_premise.reasons.length - 6} more damage locations</li>
        )}
      </ul>
      <dl className="counts">
        <dt>Lose power initially</dt>
        <dd>{r.initially_interrupted}</dd>
        <dt>{STATUS_TEXT.repair_dependent}</dt>
        <dd>{r.repair_dependent}</dd>
        <dt>{STATUS_TEXT.isolation_candidate}</dt>
        <dd>{r.isolation_candidates}</dd>
        <dt>{STATUS_TEXT.unresolved}</dt>
        <dd>{r.unresolved}</dd>
        <dt>{STATUS_TEXT.not_interrupted}</dt>
        <dd>{r.not_interrupted}</dd>
      </dl>
      {r.critical_facilities.length > 0 && (
        <p className="small">
          Critical facilities:{" "}
          {r.critical_facilities.map((c) => `${c.kind.replace("_", " ")} - ${STATUS_TEXT[c.status].toLowerCase()}`).join("; ")}.
        </p>
      )}
      <h4>Step restoration (simplified)</h4>
      <p className="small">{r.step_restoration}</p>
      <p className="small muted">{r.disclaimer}</p>
      <ul className="small muted">
        {r.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </details>
  );
}
