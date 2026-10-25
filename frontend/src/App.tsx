import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, isAbort } from "./api";
import { commsReducer, initialComms, lastNotified } from "./commsState";
import { AlertsCard, LatestAlert } from "./components/AlertsCard";
import { AssistantPanel } from "./components/AssistantPanel";
import { AuditCard } from "./components/AuditCard";
import { FactsPanel } from "./components/FactsPanel";
import { GuidanceCard, TopActions } from "./components/GuidanceCard";
import { JourneyTabs, type TabDef, type TabId } from "./components/JourneyTabs";
import { NetworkMap } from "./components/NetworkMap";
import { PreferencesCard } from "./components/PreferencesCard";
import { PremiseSelector } from "./components/PremiseSelector";
import { EstimateHeadline, RestorationCard } from "./components/RestorationCard";
import { BAND_ICON, RiskDetails, RiskSummary, SeverityControl } from "./components/RiskCard";
import { IMPACT_TEXT, ScenarioImpact, ScenarioPanel } from "./components/ScenarioPanel";
import { crewComparison, restorationOutlook } from "./outlook";
import { createLatest, initialScenarioState, scenarioReducer } from "./scenarioState";
import type {
  AlertPrefs,
  BriefingRequest,
  BriefingResponse,
  Preferences,
  PreviousEstimate,
  CircuitMap,
  CircuitSummary,
  CrewParams,
  PremiseContext,
  PremiseListItem,
  RiskResult,
  ScenarioOption,
  SeverityOption,
} from "./types";

// Deterministic demo premise on Circuit 18: overhead supply path with many
// historical (Feb 2025) damage records upstream.
const DEMO_PREMISE = "PRM-00770FFC";
const NO_PREFS: Preferences = { medical_power_dependent: false, accessibility: [] };
const NO_ALERTS: AlertPrefs = { opt_in: false, channel: "none" };

export default function App() {
  const [circuits, setCircuits] = useState<CircuitSummary[]>([]);
  const [circuitId, setCircuitId] = useState<string | null>(null);
  const [premises, setPremises] = useState<PremiseListItem[]>([]);
  const [layers, setLayers] = useState<CircuitMap | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [ctx, setCtx] = useState<PremiseContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const premiseCircuit = ctx?.premise.circuit_id ?? null; // the selected premise's own circuit

  const params = useRef(new URLSearchParams(window.location.search)).current;
  const [severity, setSeverity] = useState(params.get("severity") ?? "moderate");
  const [severityOptions, setSeverityOptions] = useState<SeverityOption[]>([]);
  const [risk, setRisk] = useState<RiskResult | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);

  const [scenarioOptions, setScenarioOptions] = useState<ScenarioOption[]>([]);
  const [scen, dispatch] = useReducer(scenarioReducer, initialScenarioState);
  const [showHistorical, setShowHistorical] = useState(true);
  const [tab, setTab] = useState<TabId>(() => (params.get("scenario") ? "explore" : "overview"));

  const premiseLatest = useRef(createLatest()).current;
  const riskLatest = useRef(createLatest()).current;
  const simLatest = useRef(createLatest()).current;
  const [crew, setCrew] = useState<CrewParams>({
    crews: Number(params.get("crews") ?? 2),
    crew_size: Number(params.get("crew_size") ?? 4),
    hours_per_day: 16,
    access_delay_h: Number(params.get("access_delay") ?? 0),
    access_scope: params.get("access_scope") === "all" ? "all" : "reported",
    prioritize_critical: params.get("priority") !== "off",
    restring_assumption: params.get("restring") !== "off",
  });

  useEffect(() => {
    api
      .circuits()
      .then((cs) => {
        setCircuits(cs);
        if (cs.length) setCircuitId(cs[0].circuit_id);
      })
      .catch((e) => setError(`Could not reach the backend (${e.message}). Is it running on port 8000?`));
  }, []);

  useEffect(() => {
    if (!circuitId) return;
    Promise.all([api.premises(circuitId), api.map(circuitId)])
      .then(([ps, m]) => {
        setPremises(ps);
        setLayers(m);
      })
      .catch((e) => setError(e.message));
  }, [circuitId]);

  const select = useCallback(
    (id: string) => {
      setSelectedId(id);
      const url = new URL(window.location.href);
      url.searchParams.set("premise", id);
      window.history.replaceState(null, "", url);
      dispatch({ type: "premiseChanged" }); // presets are per premise; an active scenario stays fixed
      setScenarioOptions([]);
      setLoading(true);
      setError(null);
      const req = premiseLatest.start();
      Promise.all([api.premise(id, req.signal), api.scenarios(id, req.signal)])
        .then(([c, sc]) => {
          if (!req.isCurrent()) return;
          setCtx(c);
          setScenarioOptions(sc.scenarios);
        })
        .catch((e) => {
          if (isAbort(e) || !req.isCurrent()) return;
          setCtx(null);
          setError(e.message);
        })
        .finally(() => req.isCurrent() && setLoading(false));
    },
    [premiseLatest],
  );

  // Deep links for repeatable demos: ?premise=PRM-XXXXXXXX&severity=severe&scenario=neighbouring_branch
  // (the scenario runs once with its default locations).
  const deepScenario = useRef(params.get("scenario"));
  useEffect(() => {
    const id = params.get("premise");
    if (id) select(id);
  }, [select, params]);
  useEffect(() => {
    const want = deepScenario.current;
    const opt = want ? scenarioOptions.find((o) => o.id === want && o.available) : undefined;
    if (opt) {
      deepScenario.current = null;
      dispatch({ type: "choose", scenario: opt });
      dispatch({ type: "activate", label: opt.label });
    }
  }, [scenarioOptions]);

  // Pre-storm risk depends on premise + severity only (never on a simulated scenario).
  useEffect(() => {
    if (!selectedId) return;
    const req = riskLatest.start();
    setRiskLoading(true);
    api
      .risk(selectedId, severity, req.signal)
      .then((r) => {
        if (!req.isCurrent()) return;
        setRisk(r);
        setSeverityOptions(r.severity_options);
      })
      .catch((e) => {
        if (isAbort(e) || !req.isCurrent()) return;
        setRisk(null);
        setError(e.message);
      })
      .finally(() => req.isCurrent() && setRiskLoading(false));
  }, [selectedId, severity, riskLatest]);

  // The active (fixed) scenario is re-evaluated whenever the premise or crew inputs change.
  // Every request gets a fresh id; the reducer drops responses that are no longer current.
  const reqCounter = useRef(0);
  const scenRequestId = useRef(scen.requestId);
  scenRequestId.current = scen.requestId;
  useEffect(() => {
    if (!scen.active || !selectedId || !premiseCircuit) {
      simLatest.cancel();
      return;
    }
    const requestId = Math.max(reqCounter.current, scenRequestId.current) + 1;
    reqCounter.current = requestId;
    dispatch({ type: "requestStarted", requestId });
    const req = simLatest.start();
    api
      .simulate(premiseCircuit, selectedId, scen.active, crew, req.signal)
      .then((result) => dispatch({ type: "loaded", requestId, result }))
      .catch((e) => {
        if (!isAbort(e)) dispatch({ type: "failed", requestId, error: e.message });
      });
  }, [scen.active, selectedId, premiseCircuit, crew, simLatest]);

  const simulated = scen.result?.impact ?? null;

  // Choosing another circuit in the dropdown starts over there: the selected home belongs to the old
  // circuit (and would pull the circuit straight back), and so do the damage locations of an active
  // scenario. The home picker opens on the new circuit's homes.
  const [pickerSignal, setPickerSignal] = useState(0);
  const changeCircuit = (id: string) => {
    if (id === circuitId) return;
    premiseLatest.cancel();
    setSelectedId(null);
    setCtx(null);
    setRisk(null);
    setBrief(null);
    setScenarioOptions([]);
    setPremises([]);
    setLayers(null);
    setLoading(false);
    dispatch({ type: "reset" });
    const url = new URL(window.location.href);
    url.searchParams.delete("premise");
    window.history.replaceState(null, "", url);
    setCircuitId(id);
    setPickerSignal((n) => n + 1);
  };

  // The selected premise's own circuit drives the map and simulations. A pinned scenario's damage
  // locations belong to one circuit, so moving to a premise on another circuit resets it.
  const lastCircuit = useRef<string | null>(null);
  useEffect(() => {
    if (!premiseCircuit) return;
    if (premiseCircuit !== circuitId) setCircuitId(premiseCircuit);
    if (lastCircuit.current && lastCircuit.current !== premiseCircuit) dispatch({ type: "reset" });
    lastCircuit.current = premiseCircuit;
  }, [premiseCircuit, circuitId]);

  // ---- Milestone 4: guidance, alerts and assistant (session-only state, no browser storage)
  // Demo deep link may preset these (?medical=1&alerts=sms); they are never stored.
  const [prefs, setPrefs] = useState<Preferences>(() => ({ ...NO_PREFS, medical_power_dependent: params.get("medical") === "1" }));
  const [alertPrefs, setAlertPrefs] = useState<AlertPrefs>(() => {
    const ch = params.get("alerts");
    return ch && ["sms", "email", "push", "voice"].includes(ch) ? { opt_in: true, channel: ch as AlertPrefs["channel"] } : NO_ALERTS;
  });
  const [comms, commsDispatch] = useReducer(commsReducer, initialComms);
  const [brief, setBrief] = useState<BriefingResponse | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const briefLatest = useRef(createLatest()).current;

  // simulated lifecycle history belongs to one premise and one scenario
  useEffect(() => commsDispatch({ type: "clearAll" }), [selectedId]);
  useEffect(() => commsDispatch({ type: "clearScenario" }), [scen.active]);

  const scenarioKey = brief?.scenario_key ?? null;
  const notified = useMemo(() => lastNotified(comms.log, scenarioKey), [comms.log, scenarioKey]);
  const briefingRequest = useMemo<BriefingRequest | null>(
    () =>
      selectedId
        ? {
            premise_id: selectedId,
            severity,
            simulation: scen.active
              ? {
                  scenario_id: scen.active.scenarioId,
                  scenario_label: scen.active.label,
                  location_ids: scen.active.locationIds,
                  crew,
                }
              : null,
            preferences: prefs,
            alerts: alertPrefs,
            events: comms.events,
            last_notified: notified,
          }
        : null,
    [selectedId, severity, scen.active, crew, prefs, alertPrefs, comms.events, notified],
  );

  useEffect(() => {
    if (!briefingRequest) return;
    const req = briefLatest.start();
    setBriefLoading(true);
    api
      .briefing(briefingRequest, req.signal)
      .then((b) => {
        if (!req.isCurrent()) return;
        setBrief(b);
        setBriefError(null);
        commsDispatch({ type: "deliver", messages: b.alerts.messages, scenarioKey: b.scenario_key });
      })
      .catch((e) => {
        if (isAbort(e) || !req.isCurrent()) return;
        setBriefError(e.message);
      })
      .finally(() => req.isCurrent() && setBriefLoading(false));
  }, [briefingRequest, briefLatest]);

  // Previous estimate for "why did my estimate change?". History advances only when an
  // estimate-relevant input changes (premise, severity, scenario, crew) and only from a
  // restoration result whose echoed crew inputs match the current ones (no mixed states).
  const estimateHistory = useRef<{ key: string; prev: PreviousEstimate | null; cur: PreviousEstimate | null }>({
    key: "",
    prev: null,
    cur: null,
  });
  const res = scen.result?.restoration ?? null;
  const resMatches = !scen.active || (res !== null && JSON.stringify(res.params) === JSON.stringify(crew));
  const estimateKey = JSON.stringify([selectedId, severity, brief?.scenario_key ?? null, scen.active ? crew : null]);
  if (brief && resMatches && risk && estimateHistory.current.key !== estimateKey) {
    const sel = scen.active ? res?.selected : undefined;
    estimateHistory.current = {
      key: estimateKey,
      prev: estimateHistory.current.cur,
      cur: {
        snapshot_version: brief.snapshot_version,
        severity,
        crew: scen.active ? crew : null,
        scenario_key: brief.scenario_key,
        range_kind: sel?.range_kind ?? null,
        lower_h: sel?.lower_h ?? null,
        upper_h: sel?.upper_h ?? null,
        risk_band: risk.band,
      },
    };
  }
  const interruptedHere = !!simulated && simulated.selected_premise.status !== "not_interrupted";
  const outageConfirmed = !!scenarioKey && comms.events.some((e) => e.type === "outage_confirmed" && e.scenario_key === scenarioKey);
  const restored = !!scenarioKey && comms.events.some((e) => e.type === "restoration_confirmed" && e.scenario_key === scenarioKey);

  const restorationResult = scen.result?.restoration ?? null;
  const simLoading = scen.status === "loading";
  const outlook = restorationOutlook(!!scen.active, restorationResult, simLoading, scen.error);
  const comparison = simLoading ? null : crewComparison(estimateHistory.current.prev, estimateHistory.current.cur);
  const contextLabel = selectedId
    ? [
        `your home (demo ID ${selectedId})`,
        `simulated storm severity "${risk?.severity_label ?? severity}"`,
        scen.active ? `simulated damage "${scen.active.label}" with ${crew.crews} crew${crew.crews === 1 ? "" : "s"} of ${crew.crew_size}` : "no simulated damage",
      ].join(", ")
    : null;

  // Links that open another tab move focus to a sensible target there (a control if it is visible
  // and enabled, otherwise the tab's heading), so keyboard and screen-reader users land in context.
  const [focusTarget, setFocusTarget] = useState<{ id: string; fallback: string } | null>(null);
  const goTo = (t: TabId, id: string, fallback: string) => {
    setTab(t);
    setFocusTarget({ id, fallback });
  };
  useEffect(() => {
    if (!focusTarget) return;
    const el = document.getElementById(focusTarget.id) as HTMLElement | null;
    const usable = el && el.offsetParent !== null && !(el as HTMLInputElement).disabled;
    (usable ? el : document.getElementById(focusTarget.fallback))?.focus();
    setFocusTarget(null);
  }, [focusTarget]);
  const toExplore = () => goTo("explore", "scenario-select", "explore-title");
  const toCrews = () => goTo("explore", "crew-crews", "explore-title");

  const [prefsOpen, setPrefsOpen] = useState(
    () => prefs.medical_power_dependent || prefs.accessibility.length > 0 || alertPrefs.opt_in,
  );
  const openPrefs = () => {
    setPrefsOpen(true);
    requestAnimationFrame(() => document.querySelector<HTMLElement>("#prefs > summary")?.focus());
  };

  const overview = !selectedId ? (
    <section className="card empty">
      <h2>Choose your home to begin</h2>
      <p className="muted">
        Pick a home with the selector or load the demo home to see whether you could lose power, how long restoration
        could take, how to prepare and whether you qualify for alerts.
      </p>
    </section>
  ) : (
    <div className="overview">
      <section className="card" aria-labelledby="ov-risk">
        <h2 id="ov-risk">Will I lose power?</h2>
        <RiskSummary risk={risk} loading={riskLoading} />
        <details>
          <summary>Explanations and model details</summary>
          <RiskDetails risk={risk} />
        </details>
      </section>

      <section className="card" aria-labelledby="ov-rest">
        <h2 id="ov-rest">How long could restoration take?</h2>
        {!scen.active ? (
          <>
            <p className="small">
              It depends on what the storm damages. Try a simulated damage scenario to see an estimate for your home.
            </p>
            <button type="button" onClick={toExplore}>
              Explore a scenario
            </button>
          </>
        ) : (
          <>
            {simulated && (
              <p className={`impact impact-${simulated.selected_premise.status}`}>{IMPACT_TEXT[simulated.selected_premise.status]}</p>
            )}
            {restorationResult ? (
              <div className={simLoading ? "stale" : undefined}>
                <EstimateHeadline r={restorationResult} />
              </div>
            ) : (
              <p className="muted small">{scen.error ? `The simulation failed (${scen.error}).` : "Calculating..."}</p>
            )}
            <p className="small">
              <button type="button" className="link-btn" onClick={toCrews}>
                See what could change this
              </button>
            </p>
          </>
        )}
      </section>

      <section className="card" aria-labelledby="ov-prep">
        <h2 id="ov-prep">What should I do to prepare?</h2>
        <TopActions briefing={brief} loading={briefLoading} error={briefError} />
        {brief && (
          <details>
            <summary>Full preparation checklist ({brief.guidance.length})</summary>
            <GuidanceCard briefing={brief} loading={briefLoading} error={briefError} />
          </details>
        )}
      </section>

      <section className="card" aria-labelledby="ov-alert">
        <h2 id="ov-alert">Do I qualify for outage alerts?</h2>
        <LatestAlert briefing={brief} log={comms.log} alerts={alertPrefs} onAlerts={setAlertPrefs} />
        <details>
          <summary>Alert history and notification preferences ({comms.log.length} logged)</summary>
          <p className="small">
            Alerts: {alertPrefs.opt_in ? "opted in" : "not opted in"}.{" "}
            <button type="button" className="link-btn" onClick={openPrefs}>
              Change needs and alert preferences
            </button>
          </p>
          <AlertsCard
            briefing={brief}
            log={comms.log}
            canConfirmOutage={interruptedHere && !!scenarioKey}
            outageConfirmed={outageConfirmed}
            restored={restored}
            onConfirmOutage={() =>
              scenarioKey && commsDispatch({ type: "event", event: { type: "outage_confirmed", scenario_key: scenarioKey } })
            }
            onConfirmRestored={() =>
              scenarioKey &&
              commsDispatch({ type: "event", event: { type: "restoration_confirmed", scenario_key: scenarioKey } })
            }
          />
        </details>
      </section>
    </div>
  );

  const explore = (
    <div className="explore">
      <div className="explore-controls">
        <section className="card" aria-labelledby="explore-title">
          <h2 id="explore-title" tabIndex={-1}>
            Explore scenarios <span className="tag tag-assume">simulation, not a real outage</span>
          </h2>
          <SeverityControl severity={severity} options={severityOptions} onSeverity={setSeverity} />
          <h3>Damage scenario</h3>
          <ScenarioPanel options={scenarioOptions} state={scen} dispatch={dispatch} disabled={!ctx || loading} />
        </section>
        <section className="card result" aria-labelledby="explore-result">
          <h2 id="explore-result">How long could restoration take? (simulated)</h2>
          {simulated && (
            <p className={`impact impact-${simulated.selected_premise.status}`}>{IMPACT_TEXT[simulated.selected_premise.status]}</p>
          )}
          <RestorationCard
            result={restorationResult}
            loading={simLoading}
            active={!!scen.active}
            crew={crew}
            onCrew={setCrew}
            pendingMessage={ctx ? "Choose a damage scenario and select Simulate damage to see an estimate for your home." : "Choose your home first."}
            comparison={comparison}
          />
          {simulated && <ScenarioImpact r={simulated} stale={simLoading} />}
        </section>
      </div>

      <section className="explore-map" aria-label="Network map">
        <p className={`map-banner small ${scen.active ? "sim" : ""}`}>
          {scen.active
            ? `SIMULATED damage shown: ${scen.active.label}. Not a real outage.`
            : "No simulated damage. Dashed pink circles are historical damage records, not current damage."}
        </p>
        {layers ? (
          <NetworkMap
            layers={layers}
            context={ctx}
            premises={premises}
            onSelect={select}
            scenario={simulated}
            showHistorical={showHistorical}
          />
        ) : (
          <div className="map placeholder">Loading map...</div>
        )}
        <div className="legend small">
          <span>
            <span className="sw sw-oh" /> overhead line
          </span>
          <span>
            <span className="sw sw-ug" /> underground line
          </span>
          <span>
            <span className="sw sw-path" /> your supply path
          </span>
          <span>
            <span className="sw sw-fuse" /> fuse <span className="sw sw-rec" /> recloser
          </span>
        </div>
        <div className="legend small">
          <label>
            <input type="checkbox" checked={showHistorical} onChange={(e) => setShowHistorical(e.target.checked)} />
            <span className="sw sw-dmg" /> Historical damage (past records, approx. location)
          </label>
          <span>
            <span className="sw sw-sim" /> Simulated damage {scen.active ? "(active scenario)" : "(none active)"}
          </span>
          {simulated && (
            <span>
              transformers: <span className="sw sw-i-rep" /> power back after repair <span className="sw sw-i-unr" /> unclear if
              sooner <span className="sw sw-i-iso" /> may come back sooner (power rerouted)
            </span>
          )}
        </div>
      </section>
    </div>
  );

  const ask = (
    <AssistantPanel
      request={briefingRequest}
      snapshotVersion={brief?.snapshot_version ?? null}
      previous={estimateHistory.current.prev}
      contextLabel={contextLabel}
      scenarioActive={!!scen.active}
    />
  );

  const tabs: TabDef[] = [
    { id: "overview", label: "Overview", panel: overview },
    { id: "explore", label: "Explore scenarios", panel: explore },
    { id: "ask", label: "Ask", panel: ask },
    { id: "audit", label: "Audit trail", panel: <AuditCard active={tab === "audit"} /> },
  ];

  return (
    <div className="app">
      <a className="skip" href="#journey">
        Skip to results
      </a>
      <header className="topbar">
        <div>
          <h1>Outage Concierge</h1>
          <p className="muted small">
            Hackathon prototype on anonymized, historical challenge data. Not an official AEP service and not live outage
            information.
          </p>
        </div>
      </header>

      <div className="context">
        <div className="context-row">
          {circuits.length > 1 && (
            <label className="circuit-pick">
              <span className="muted small">Circuit</span>
              <select value={circuitId ?? ""} onChange={(e) => changeCircuit(e.target.value)}>
                {circuits.map((c) => (
                  <option key={c.circuit_id} value={c.circuit_id}>
                    {c.label} ({c.premises} homes &amp; businesses)
                  </option>
                ))}
              </select>
            </label>
          )}
          <PremiseSelector
            premises={premises}
            selectedId={selectedId}
            onSelect={select}
            demoId={DEMO_PREMISE}
            openSignal={pickerSignal}
          />
          <div className={`status ${scen.active ? "sim" : "pre"}`} role="status">
            {scen.active ? (
              <>
                <span>
                  <strong>SIMULATION:</strong> {scen.active.label}
                  {simulated &&
                    ` - in this simulation, ${simulated.initially_interrupted} of the ${simulated.circuit_premises} homes and businesses on your line lose power. Not a real outage.`}
                </span>
                <button type="button" className="secondary tiny" onClick={() => dispatch({ type: "reset" })}>
                  Reset scenario
                </button>
              </>
            ) : (
              <span>
                <strong>Pre-storm view.</strong> No simulated damage is active.
              </span>
            )}
          </div>
        </div>

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {loading && (
          <p className="muted small" role="status">
            Loading premise...
          </p>
        )}

        {selectedId && (
          <div className="summary" role="region" aria-label="Results summary">
            <div className="sum-item">
              <span className="sum-label">Pre-storm risk</span>
              {risk?.status === "calculated" && risk.band && risk.confidence ? (
                <span className={riskLoading ? "stale" : undefined}>
                  <span className={`band band-${risk.band} band-sm`}>
                    <span aria-hidden>{BAND_ICON[risk.band]}</span> {risk.band}
                  </span>{" "}
                  <span className="conf">confidence {risk.confidence.level}</span>
                </span>
              ) : (
                <span className="small">{risk ? "Insufficient information" : riskLoading ? "Calculating..." : "-"}</span>
              )}
            </div>
            <div className="sum-item">
              <span className="sum-label">Restoration (simulated)</span>
              {outlook.state === "none" ? (
                <span className="small">
                  {outlook.text}.{" "}
                  {tab !== "explore" && (
                    <button type="button" className="link-btn" onClick={toExplore}>
                      Explore a scenario
                    </button>
                  )}
                </span>
              ) : (
                <span className={outlook.stale ? "stale" : undefined}>
                  <strong>{outlook.text}</strong>
                  {outlook.qualifier && <span className="small"> ({outlook.qualifier})</span>}
                  {outlook.confidence && <span className="conf"> confidence {outlook.confidence}</span>}
                </span>
              )}
            </div>
          </div>
        )}

        {selectedId && (
          <div className="context-row ctx-details">
            {ctx && !loading && (
              <details className="ctx-item">
                <summary>
                  <span className="prefs-title">Premise details</span>{" "}
                  <span className="muted small">
                    {ctx.premise.circuit_label}, {ctx.premise.service_type.toLowerCase()} service
                  </span>
                </summary>
                <FactsPanel ctx={ctx} />
              </details>
            )}
            <PreferencesCard
              prefs={prefs}
              alerts={alertPrefs}
              onPrefs={setPrefs}
              onAlerts={setAlertPrefs}
              onReset={() => {
                setPrefs(NO_PREFS);
                setAlertPrefs(NO_ALERTS);
              }}
              open={prefsOpen}
              onOpen={setPrefsOpen}
            />
          </div>
        )}
      </div>

      <main className="main" id="journey">
        <JourneyTabs tabs={tabs} active={tab} onChange={setTab} />
      </main>
    </div>
  );
}
