import { Fragment, useState } from "react";
import { fmtHours as fmt, KIND_LABEL, LOWER_BOUND_NOTE } from "../outlook";
import type { CrewParams, RestorationResult } from "../types";

interface Props {
  result: RestorationResult | null;
  loading: boolean;
  active: boolean;
  crew: CrewParams;
  onCrew: (c: CrewParams) => void;
  pendingMessage: string;
  comparison: string | null; // "Before this change: ..." after a crew/access edit
}

function NumberField(props: {
  id?: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="field compact">
      <span>
        {props.label} <span className="muted">({props.min}-{props.max})</span>
      </span>
      <input
        id={props.id}
        type="number"
        value={props.value}
        min={props.min}
        max={props.max}
        step={props.step ?? 1}
        onChange={(e) => {
          const v = Number(e.target.value);
          if (Number.isFinite(v)) props.onChange(Math.min(props.max, Math.max(props.min, v)));
        }}
      />
    </label>
  );
}

export function CrewControls({ crew, onCrew }: { crew: CrewParams; onCrew: (c: CrewParams) => void }) {
  const set = (k: keyof CrewParams) => (v: number | string) => onCrew({ ...crew, [k]: v });
  return (
    <fieldset className="crew-controls">
      <legend className="small">What could change your estimate? (what-if inputs)</legend>
      <div className="grid2">
        <NumberField id="crew-crews" label="Repair crews available" value={crew.crews} min={1} max={20} onChange={set("crews")} />
        <NumberField label="Workers per crew" value={crew.crew_size} min={2} max={8} onChange={set("crew_size")} />
      </div>
      <details>
        <summary>More what-ifs: access delays and work hours</summary>
        <div className="grid2">
          <NumberField label="Crew work hours per day" value={crew.hours_per_day} min={8} max={16} onChange={set("hours_per_day")} />
          <NumberField label="Extra delay reaching damage, hours (e.g. blocked roads)" value={crew.access_delay_h} min={0} max={48} step={2} onChange={set("access_delay_h")} />
        </div>
        <label className="small loc-option">
          <input
            type="checkbox"
            checked={crew.access_scope === "all"}
            onChange={(e) => set("access_scope")(e.target.checked ? "all" : "reported")}
          />
          Apply that delay to every repair (otherwise only where access problems were reported)
        </label>
        <label className="small loc-option">
          <input
            type="checkbox"
            checked={crew.prioritize_critical}
            onChange={(e) => onCrew({ ...crew, prioritize_critical: e.target.checked })}
          />
          Crews fix damage affecting hospitals, fire stations and ambulance stations first
        </label>
        <label className="small loc-option">
          <input
            type="checkbox"
            checked={crew.restring_assumption}
            onChange={(e) => onCrew({ ...crew, restring_assumption: e.target.checked })}
          />
          Include our assumed time for replacing damaged wire (not in AEP's labor data)
        </label>
      </details>
    </fieldset>
  );
}

function Timeline({ r, bound }: { r: RestorationResult; bound: "optimistic" | "conservative" }) {
  const jobs = r.jobs.filter((j) => j[bound]);
  if (!jobs.length) return <p className="muted small">No schedulable jobs.</p>;
  const end = Math.max(...jobs.map((j) => j[bound]!.end_h), r.selected.upper_h ?? 0, 1);
  const crews = Array.from(new Set(jobs.map((j) => j[bound]!.crew))).sort((a, b) => a - b);
  const controlling = new Set(r.selected.controlling_jobs);
  const days = Math.floor(end / 24);
  return (
    <div className="timeline" role="img" aria-label={`${bound} crew schedule`}>
      {crews.map((c) => (
        <div className="tl-row" key={c}>
          <span className="tl-label small">Crew {c}</span>
          <div className="tl-track">
            {Array.from({ length: days }, (_, d) => (
              <span key={d} className="tl-day" style={{ left: `${(100 * 24 * (d + 1)) / end}%` }} />
            ))}
            {jobs
              .filter((j) => j[bound]!.crew === c)
              .map((j) => {
                const slot = j[bound]!;
                return (
                  <span
                    key={j.id}
                    className={`tl-bar ${controlling.has(j.id) ? "tl-yours" : ""}`}
                    style={{ left: `${(100 * slot.start_h) / end}%`, width: `${Math.max(0.6, (100 * (slot.end_h - slot.start_h)) / end)}%` }}
                    title={`${j.label} (${j.id}): ${fmt(slot.start_h)} - ${fmt(slot.end_h)}, ${j.customers_waiting} customers waiting`}
                  />
                );
              })}
          </div>
        </div>
      ))}
      <div className="tl-axis small muted">
        <span>0 h</span>
        <span>{fmt(end)}</span>
      </div>
      <p className="muted small">
        Highlighted bars are the repairs your estimate depends on. Gaps are waiting time (assessment, weather, material,
        access) or off-shift hours; dashed lines mark day boundaries.
      </p>
    </div>
  );
}

const CRITICAL_LABEL = { hospital: "Hospital", fire_station: "Fire station", ambulance_station: "Ambulance station" } as const;

const crewsText = (n: number | null, complete: boolean) =>
  n === null ? "more than 20 crews" : `${complete ? "" : "at least "}${n} crew${n === 1 ? "" : "s"}`;

/** The estimate and its limitations, kept together (also used on Overview). */
export function EstimateHeadline({ r }: { r: RestorationResult }) {
  const s = r.selected;
  return (
    <>
      {s.range_kind !== "lower_bound_only" && <p className="kind-label small">{KIND_LABEL[s.range_kind]}</p>}
      {s.range_kind === "conditional" && s.conditional ? (
        <dl className="outcomes">
          <dt>If crews can reroute power around the damage</dt>
          <dd className="duration">
            {fmt(s.conditional.if_isolated_low_h)} - {fmt(s.conditional.if_isolated_high_h)}
          </dd>
          <dt>Otherwise, after the repair</dt>
          <dd className="duration">
            {s.conditional.if_repair_high_h === null
              ? "cannot be estimated"
              : s.conditional.repair_scope_complete
                ? `${fmt(s.conditional.if_repair_low_h)} - ${fmt(s.conditional.if_repair_high_h)}`
                : `at least ${fmt(s.conditional.if_repair_low_h)}`}
          </dd>
        </dl>
      ) : (
        <p className="duration">{s.display}</p>
      )}
      {s.range_kind === "lower_bound_only" && <p className="small limit-note">{LOWER_BOUND_NOTE}</p>}
      {s.uses_assumption && (
        <p className="small limit-note">
          Includes our team's assumed time for replacing damaged wire; AEP's labor data has none.
          {s.workbook_only_lower_h !== null && ` From AEP's labor data alone: at least ${fmt(s.workbook_only_lower_h)}.`}
        </p>
      )}
      {s.range_kind !== "not_interrupted" && <p className="conf">Confidence: {s.confidence.level}</p>}
      <ul className="limits small">
        {s.range_kind === "conditional" && <li>Two alternative outcomes, not one range.</li>}
        {s.range_kind === "crew_infeasible" && <li>The crew size is too small for a required job.</li>}
        {s.range_kind === "insufficient_data" && <li>Insufficient information: the repair is not in the labor data.</li>}
        {s.network_uncertain && <li>Network dependency uncertain.</li>}
      </ul>
      <p className="muted small">
        {r.time_reference} Bounds come from optimistic and conservative assumptions, not a statistical interval. {r.disclaimer}
      </p>
    </>
  );
}

export function RestorationCard({ result: r, loading, active, crew, onCrew, pendingMessage, comparison }: Props) {
  const [bound, setBound] = useState<"optimistic" | "conservative">("conservative");
  return (
    <div className="restoration" aria-live="polite" aria-busy={loading}>
      {!r && (
        <>
          <p className="pending-badge">{active && loading ? "Calculating..." : "No estimate yet"}</p>
          <p className="muted small">{active ? "Calculating the repair schedule..." : pendingMessage}</p>
        </>
      )}
      {r && (
        <div className={loading ? "stale" : undefined}>
          <EstimateHeadline r={r} />
          {comparison && <p className="compare small">{comparison}</p>}
        </div>
      )}
      {active && <CrewControls crew={crew} onCrew={onCrew} />}
      {r && (
        <div className={loading ? "stale" : undefined}>
          <h4>Why this estimate?</h4>
          <ul className="small">
            {r.selected.why.slice(0, 2).map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          {r.selected.why.length > 2 && (
            <details>
              <summary>More reasons ({r.selected.why.length - 2})</summary>
              <ul className="small">
                {r.selected.why.slice(2).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </details>
          )}

          {r.warnings.length > 0 && (
            <details>
              <summary>Warnings about this estimate ({r.warnings.length})</summary>
              <ul className="warnings small">
                {r.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </details>
          )}

          {r.critical_facilities.length > 0 && (
            <>
              <h4>Critical facilities on this circuit</h4>
              <dl className="counts">
                {r.critical_facilities.map((c, i) => (
                  <Fragment key={`${c.kind}-${i}`}>
                    <dt>{CRITICAL_LABEL[c.kind]}</dt>
                    <dd>{c.display}</dd>
                  </Fragment>
                ))}
              </dl>
              {r.critical_priority && <p className="small">{r.critical_priority.text}</p>}
              <p className="muted small">
                {r.params.prioritize_critical ? "Their repairs go first." : "Critical-facility priority is off."} Facility type
                only; locations are not shown. Each is linked to its nearest service transformer (an approximation).
              </p>
            </>
          )}

          <details>
            <summary>Whole scenario and labor totals</summary>
            <dl className="counts">
              <dt>All repairs finished</dt>
              <dd>
                {r.overall.lower_h === null
                  ? "n/a"
                  : r.overall.complete
                    ? `${fmt(r.overall.lower_h)} - ${fmt(r.overall.upper_h)}`
                    : `at least ${fmt(r.overall.lower_h)}`}
              </dd>
              <dt>Repair jobs</dt>
              <dd>
                {r.overall.jobs}
                {r.overall.jobs_partial > 0 && ` (${r.overall.jobs_partial} partly modeled)`}
                {r.overall.jobs_unsupported + r.overall.jobs_infeasible > 0 &&
                  ` (${r.overall.jobs_unsupported + r.overall.jobs_infeasible} not estimable)`}
              </dd>
              <dt>Total labor effort</dt>
              <dd>
                {r.overall.person_hours_low.toFixed(0)}-{r.overall.person_hours_high.toFixed(0)} person-h
              </dd>
            </dl>
            {r.overall.note && <p className="muted small">{r.overall.note}</p>}
            <p className="muted small">Labor effort is work by all crews combined; it is not the same as elapsed time.</p>
          </details>

          {r.crew_targets && (
            <details>
              <summary>Crews needed to finish all modeled repairs</summary>
              <div className="table-wrap">
                <table className="jobs small">
                  <thead>
                    <tr>
                      <th>Within</th>
                      <th>Optimistic</th>
                      <th>Conservative</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.crew_targets.targets.map((t) => (
                      <tr key={t.label}>
                        <td>{t.label}</td>
                        <td>{crewsText(t.crews_needed_optimistic, r.crew_targets!.scope_complete)}</td>
                        <td>{crewsText(t.crews_needed_conservative, r.crew_targets!.scope_complete)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">{r.crew_targets.note}</p>
            </details>
          )}

          {r.backtest && (
            <details>
              <summary>Check against the real repair pace ({r.backtest.event})</summary>
              <p className="small">
                The damage records say {r.backtest.records_used} of these repairs were finished by day{" "}
                {r.backtest.observed_finish_day} after the storm's first report. This model matches that pace with{" "}
                <strong>
                  {r.backtest.implied_crews_optimistic === r.backtest.implied_crews_conservative
                    ? crewsText(r.backtest.implied_crews_optimistic, true)
                    : r.backtest.implied_crews_optimistic === null
                      ? crewsText(null, true)
                      : `${r.backtest.implied_crews_optimistic} to ${crewsText(r.backtest.implied_crews_conservative, true)}`}
                </strong>{" "}
                of {r.params.crew_size} people. With the crews you selected it finishes in{" "}
                {r.backtest.your_crews_finish_days.join(" to ")} days.
              </p>
              <div className="table-wrap">
                <table className="jobs small">
                  <caption className="small">Share of the storm's repair records closed by each day</caption>
                  <thead>
                    <tr>
                      {r.backtest.observed_pace.map((d) => (
                        <th key={d.day} scope="col">
                          Day {d.day}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      {r.backtest.observed_pace.map((d) => (
                        <td key={d.day} className="mono">
                          {Math.round(d.share_repaired * 100)}%
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                {r.backtest.note}
                {r.backtest.excluded_closure_lag > 0 &&
                  ` ${r.backtest.excluded_closure_lag} record(s) closed more than a month later were left out as paperwork, not repairs.`}
              </p>
            </details>
          )}

          <details>
            <summary>Crew schedule</summary>
            <label className="field compact">
              <span>Schedule shown</span>
              <select value={bound} onChange={(e) => setBound(e.target.value as typeof bound)}>
                <option value="conservative">conservative</option>
                <option value="optimistic">optimistic</option>
              </select>
            </label>
            <Timeline r={r} bound={bound} />
          </details>

          <details>
            <summary>Confidence and assumptions</summary>
            <ul className="small">
              {r.selected.confidence.reasons.map((c) => (
                <li key={c.text}>
                  {c.effect} - {c.text}
                </li>
              ))}
              {r.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </details>
          <details>
            <summary>Developer view: repair jobs and workbook sources</summary>
            <p className="small">
              Labor basis: <code>{r.developer.labor_basis}</code> (demo assumption). ILM {r.developer.ilm} from{" "}
              <code>{r.developer.ilm_source}</code>, applied to {r.developer.ilm_applies_to}. Source: {r.developer.source_workbook}.
            </p>
            <p className="small">
              Waits (opt, cons hours):{" "}
              {Object.entries(r.developer.waits_hours)
                .map(([k, v]) => `${k} ${v[0]}-${v[1]}`)
                .join("; ")}
              . Not applied: {Object.entries(r.developer.adders_not_applied).map(([k, v]) => `${k} (${v})`).join("; ")}.
            </p>
            <div className="table-wrap">
              <table className="jobs small">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Work</th>
                    <th>Direct h</th>
                    <th>Person-h (x{r.developer.ilm})</th>
                    <th>Waiting</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {r.jobs.map((j) => (
                    <tr key={j.id}>
                      <td className="mono">{j.id}</td>
                      <td>
                        {j.label}
                        {j.records > 1 && ` (${j.records} records merged)`}
                        <ul>
                          {j.developer.tasks.map((t) => (
                            <li key={t.name}>
                              {t.name} x{t.quantity_low}
                              {t.quantity_high !== t.quantity_low && `-${t.quantity_high}`} @{" "}
                              {t.unit_hours_low === null ? "missing" : t.unit_hours_low}
                              {t.unit_hours_high !== t.unit_hours_low && t.unit_hours_high !== null && `-${t.unit_hours_high}`} h{" "}
                              <span className="muted">[{t.source}]</span>
                              {t.drawing && <span className="muted"> [drawing: {t.drawing}]</span>}
                            </li>
                          ))}
                          {j.developer.structures.map((st) => (
                            <li key={st} className="muted">
                              structure: {st}
                            </li>
                          ))}
                          {j.developer.adders.map((a) => (
                            <li key={a.name}>
                              adder {a.name} {a.hours} h <span className="muted">[{a.source}]</span>
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td>
                        {j.direct_hours_low}-{j.direct_hours_high}
                      </td>
                      <td>
                        {j.person_hours_low}-{j.person_hours_high}
                      </td>
                      <td>
                        {Object.entries(j.waits)
                          .filter(([, v]) => v[1] > 0)
                          .map(([k, v]) => `${k} ${v[0]}-${v[1]}`)
                          .join(", ")}
                      </td>
                      <td>{[...j.problems, ...j.partial, ...j.notes].join(" ") || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
