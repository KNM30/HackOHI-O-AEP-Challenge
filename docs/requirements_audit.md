# Challenge requirements audit

Reviewed October 24, 2026 against the five-page AEP challenge brief (`aep_challenge.pdf`) and the four-page printed
AEP AI Outage Concierge Data Guide. This replaces the earlier audit from the same day; every finding it raised has
been fixed and re-tested (see [Resolved findings](#resolved-findings)).

## Verdict

**The project meets the brief's requirements and minimum demonstration, and uses every supplied data source.** The
data guide's chain (GIS -> upstream topology -> damage matching -> structures -> workbook labor x 4.5 -> step
restoration -> crew scenarios with critical-facility priority) is implemented end to end, and each step can be
traced in the developer view or in tests.

What remains open is outside the code: a browser walkthrough of the whole journey, and one live AI call with a
configured key (see [Not verified](#not-verified)). The guide asks for a focused, explainable prototype rather than a
production outage system, so a two-circuit app subset, a risk model trained on a damage-based proxy label, and
approximate secondary attribution are disclosed design limits, not gaps.

**Update (M6, same day):** after reviewing a teammate's version of the challenge, the risk model is now fitted on every
circuit and validated on held-out storms, the replay is checked against the recorded repair pace, and the API keeps
an audit trail. See [Merged from the teammate's version](#merged-from-the-teammates-version).

## Verification performed

| Check | Result |
|---|---|
| Backend tests | **149 passed** (`..\.venv\Scripts\python -m pytest -q` from `backend`) |
| Risk model validation | Leave-one-storm-out over 11 storms, 99,857 premises: pooled AUC 0.878, mean within-storm AUC 0.628 (heuristic 0.618); recalibrated predictions match observed share hit within a few points below 45% ([risk_model.md](risk_model.md)) |
| Replay pace check | Circuit 18, Feb 2025: 103 repairs recorded as finished by day 4; the model matches that with 3 to 6 four-person crews ([restoration_model.md](restoration_model.md#7-check-against-the-real-repair-pace-replay-only)) |
| Audit trail | Per-session entries for risk, simulation, briefing and assistant; typed question text never stored (tested) |
| Frontend tests | **19 passed** across three files (`npm test`) |
| Production build | **Passed** TypeScript check and Vite build (`npm run build`) |
| Real-data API probes | All scenarios evaluated on both circuits; crew count, crew size, access delay and priority changed results as described below |
| Critical-facility priority on real data | `critical_facility` scenario, Circuit 109, 1 crew: fire station 3.6 - 11 h with priority, 5.1 - 14 h without; the response reports `changed_order`, about 1.5 h sooner |
| Re-stringing assumption | On (default): single-span line damage on Circuit 18 gives 2.5 - 8.4 h, labelled, with "from AEP's labor data alone: at least 1.7 h". Off: "at least 1.7 h" as before |
| Facility privacy | Facility type only; the operator-view locations carry no coordinates and no map impacts, even when re-posted under another scenario id |
| Incomplete repair scope | Whole-scenario and conditional results show lower bounds only; alert text says "at least ... may take longer"; long-outage medical guidance appears |
| Workbook provenance | Labor values come from `labor_reference.json`, extracted from the workbook; ILM 4.5 read from `Indirect Labor Multiplier!B1` and applied once per job (tested) |
| Assistant fallback | With no provider configured, returns the labelled standard answer (tested) |

Processed scope:

| Circuit | Premises | Transformers | Protective devices | Damage records (matched / on network) | Chain consistency | Critical facilities linked |
|---|---:|---:|---:|---|---:|---|
| 18 (main demo) | 893 | 292 | 77 | 118 (115 / 113) | 100% | none within 3 km |
| 109 | 1,806 | 257 | 88 | 13 (13 / 13) | 99.97% | ambulance station, fire station |

Consistency checks show the processed network agrees with the upstream file. They do not prove electrical
correctness or predictive accuracy.

## How the supplied data is used

| Source | Use in the model | Where |
|---|---|---|
| `matched_upstream.txt` | Each premise's ordered chain to the substation; protective zones; who depends on what | `pipeline/topology.py`, `pipeline/circuit.py` |
| Primary conductor | Network graph, overhead exposure for risk, phase count for repair quantities | `pipeline/circuit.py`, `backend/app/risk.py` |
| Transformers, fuses, reclosers, switches | Service points, protective devices that trip, mapped switches for step restoration | `backend/app/network.py`, `backend/app/scenarios.py` |
| Poles | Damage matching; height/class selects small, medium or large pole-replacement labor | `pipeline/matching.py`, `backend/app/restoration.py` |
| Customers | Anonymized premise list; overhead/underground service drop in the risk score. The life-support flag is never used | `pipeline/circuit.py`, `backend/app/risk.py` |
| ARCOS damage | Matched to the nearest asset of the right type (capped distance); risk-model labels and history feature over 11 storms on all circuits; storm replay scenario; repaired dates for the replay pace check | `pipeline/matching.py`, `pipeline/build_risk_model.py`, `backend/app/risk.py`, `backend/app/scenarios.py`, `backend/app/restoration.py` |
| Secondary conductor | Secondary-wire damage attributed to the nearest service transformer (within 60 m) | `pipeline/matching.py` |
| Hospitals, fire stations, ambulance | Linked to the nearest service transformer within 150 m; repair priority, facility outcomes, operator-view scenario | `pipeline/critical.py`, `backend/app/restoration.py` |
| `Install_Labor_HackOHIO.xlsx` | Install/removal hours per construction unit, labor-only adders, ILM. Its one gap (no unit for replacing primary conductor) is filled by a single labelled, switchable team assumption | `pipeline/build_labor.py`, `backend/app/labor_config.py` (`RESTRING`) |
| `structure_drawings.pdf` | Each repair task carries its D.S. assembly and drawing page; drawings decide crossarm (three-phase only) and guy/anchor (dead-end and tap structures only) | `labor_config.STRUCTURE_DRAWINGS`, `TASK_DRAWINGS` |

## Brief requirement matrix

"Meets" means demonstrated in source, API behaviour or passing tests within the stated prototype scope. It is not a
certification of real-world accuracy.

| Requirement | Status | Evidence / limitation |
|---|---|---|
| 1. Accept anonymized premise, circuit or map context | Meets | Premise selector with salted-hash IDs; circuit picker; map |
| 1. Produce a risk estimate or clearly defined band | Meets | Recalibrated chance with a 90% range and low / moderate / high bands (5% and 15% edges), from a logistic model validated on held-out storms ([risk_model.md](risk_model.md)) |
| 1. Use historical, asset, network, spatial or storm signals | Meets | Interrupting overhead exposure, distinct historical events, service-drop type, severity input |
| 1. Show factors and uncertainty | Meets | Each factor's effect in percentage points against an average premise; 90% range; separate confidence (high / moderate / low) driven by the range and data problems; model card with held-out calibration |
| 2. Duration as a range, not false precision | Meets | Optimistic-to-conservative ranges; conditional (isolate vs repair) outcomes kept apart. Line repairs get a range through a labelled re-stringing assumption, shown beside the workbook-only lower bound; incomplete scope never shows an upper bound |
| 2. Damage type/quantity, dependencies, step restoration, labor, travel/nonproductive time | Meets | Templates by damage type and phases; supply-path blockers; mapped-switch isolation; workbook hours x 4.5 ILM (covers travel and setup) |
| 2. Update when damage, crew, access or network assumptions change | Meets | Damage locations, crews, crew size, work hours, access delay, priority; topology is fixed and disclosed |
| 2. Separate model output from confirmed utility information | Meets | "Simulated" labels throughout; outage and restoration confirmations are explicit events |
| 3. Actions fit predicted risk and duration | Meets | Rule-based guidance keyed to band and duration, including unknown duration |
| 3. Safety guidance, clearly labelled emergencies | Meets | Urgency and category labels; downed-line, generator CO and life-threat items first |
| 3. Adapt to declared accessibility, medical or critical-facility needs without inferring | Meets | Medical and accessibility needs come only from the user's declaration. Critical facilities are handled at the operator level (priority and outcomes), not as a customer declaration |
| 4. Alert eligibility from documented rules | Meets | `alert_config.py`, `alerts.py`; eligibility kept separate from opt-in and channel |
| 4. Timing, channel, escalation triggers | Meets | Timing and update thresholds, channel choice, declared-medical escalation |
| 4. Pre-storm, outage-confirmed, estimate-updated, restoration-complete messages | Meets | All four templates; lifecycle and change-detection tests pass |
| 5. Understandable reasons | Meets | Plain-language factor and status explanations; technical detail behind "Developer details" |
| 5. Confidence, assumptions, missing data, conditions that could change the answer | Meets | Confidence reasons, assumptions lists, warnings, partial-scope notes on every surface |
| 5. No raw personal data, employee contacts, precise sensitive locations or internal fields | Meets tested scope | Response schemas are an allowlist; hashed IDs; home and damage points rounded to about 100 m; facility type only; privacy tests pass. Not a penetration test |
| 5. Fallback when prediction is unreliable | Meets | Insufficient-data, unsupported-job, crew-infeasible states; assistant falls back to standard answers |

### Minimum viable demonstration

| Item | Assessment |
|---|---|
| 1. Select or enter an anonymized location | Implemented |
| 2. Risk with confidence and explanation | Implemented |
| 3. Explore scenarios, receive a restoration range | Implemented on both circuits |
| 4. Preparation actions and alert eligibility | Implemented |
| 5. At least one proactive communication | Implemented (simulated delivery only) |
| 6. Privacy, safety, uncertainty and limitations | Implemented and tested |

Judges can change severity, damage locations, crews, crew size, work hours, access delay and facility priority, and
see the response update.

## Data guide matrix

| Guide expectation | Status | Assessment |
|---|---|---|
| Connect GIS, damage, topology, structures and labor into an explainable model | Meets | Every link is implemented and traceable (see data table above) |
| Treat Data1 and Data2 as one area | Meets | One layer registry, one projected CRS |
| Inspect premises, conductors, transformers, poles, devices, damage | Meets | [data_inspection_report.md](data_inspection_report.md) profiles every layer |
| Hospitals, fire, ambulance as prioritization inputs | Meets | Linked within 150 m (labelled approximation); used by the scheduler and reported per facility |
| Relate upstream file to GIS and customer dependencies | Meets | Direct equipment joins; 100% / 99.97% chain agreement |
| Damage-to-pole matching with nearest-pole fallback | Meets | Type-aware projected nearest match with distance caps; unmatched records stay unmatched |
| Broken pole: remove and replace pole and hardware | Meets | Pole install + removal, crossarm, pins, insulators, conductor re-attachment, conditional guy/anchor/grounding |
| Phases -> structure drawings -> construction units -> workbook | Meets | Phase count sets framing and quantities; each task names its D.S. assembly and drawing page beside its workbook cell |
| Apply 4.5 once to direct labor for person-hours | Meets | Tested exactly; waits are never multiplied |
| Step restoration via switches, reclosers, fuses | Meets as approximation | Repair-dependent, isolation-candidate, unresolved and unaffected premises; no assumed alternate feeds |
| Critical customers influence what is restored first | Meets | Priority rule plus a real-data scenario where it changes the order; every result says whether priority changed anything |
| Crew assumptions, 2-8 people | Meets | Crew size 2-8, per-job minimum and useful maximum, daily work windows |
| Compare 2 days, 3 days, 1 week | Meets | Crews needed for each horizon under both bounds, labelled as minimums when scope is incomplete |
| Restoration effort and value | Meets | Tasks, person-hours, schedule, customers restored per crew-hour, facility outcomes |
| Credible range that moves with crew, damage, access, network | Meets | See sensitivity below |

### The guide's four questions

| Question | Answer in the prototype |
|---|---|
| What is damaged? | Scenario or replayed damage, matched to an asset, with damage type and repair job |
| Which customers depend on it? | Upstream chains and protective zones give interrupted, repair-dependent, isolatable and unresolved counts |
| What work repairs or isolates it? | Template tasks with drawing and workbook references; mapped switches for isolation |
| With limited crews and criticality, what first and how long? | Critical facilities first (switchable), then customers per crew-hour; per-customer, per-facility and whole-scenario ranges |

## Resolved findings

| Earlier finding | Fix | Regression test |
|---|---|---|
| F1: hospital, fire and ambulance layers not used | `pipeline/critical.py` links facilities to transformers; scheduler priority; `critical_facility` operator scenario shows the order change on real data; `critical_priority` reports `changed_order` / `already_first` / `no_facility_waiting` | `test_critical_facility_repair_goes_first_when_prioritised`, `test_circuit_109_priority_changes_order_on_real_data`, `test_circuit_109_replay_reports_priority_already_first` |
| F2: whole-scenario result claimed completion with partial work | `overall.complete` requires no partial jobs; no `upper_h` when incomplete; modeled-work end reported separately | `test_partly_modeled_jobs_make_overall_a_lower_bound`, `test_fully_modeled_jobs_give_a_full_overall_range` |
| F3: incomplete conditional repair showed an upper bound | "If not: at least ..." display and alert wording; guidance treats the duration as unknown | `test_incomplete_conditional_repair_has_no_upper_bound_anywhere`, `test_complete_conditional_repair_keeps_its_range` |
| Drawings not traceable to templates | `STRUCTURE_DRAWINGS` and `TASK_DRAWINGS`, shown in the developer view | `test_every_template_task_traces_to_a_structure_drawing`, `test_drawing_reference_reaches_developer_view` |
| Most line-damage estimates were "at least" only, because the workbook has no conductor-replacement unit | Labelled, switchable re-stringing assumption (`labor_config.RESTRING`); workbook-only lower bound shown alongside | `test_restring_assumption_bounds_line_repairs_and_is_labelled`, `test_restring_assumption_keeps_ilm_once_and_scales_with_span_length`, `test_restring_toggle_on_real_data` |
| No 2-day / 3-day / 1-week comparison | `crew_targets` in every restoration result | `test_crew_targets_are_monotone_and_flag_incomplete_scope` |
| Assistant's alerts answer listed rule conditions as assumptions whether or not they applied (it could say an outage was confirmed when none was) | Each rule is labelled "Met now" or "Not met", in the standard answer and in the AI snapshot | `test_alert_answer_does_not_state_unmet_rules_as_facts` |
| Premise endpoint returned the home's exact coordinates (6 decimals), which with a browsable selector amounts to an address | Home location rounded to about 100 m, like historical damage; map label says "approximate" | `test_premise_location_is_rounded` |
| Assistant's "what changed?" answer reported an earlier "at least" estimate's modeled-work end as "latest modeled time about N h" | Only a bounded estimate's upper end is quoted; an "at least" one is quoted as "at least"; the AI snapshot drops the upper value too | `test_changed_answer_never_turns_an_at_least_estimate_into_a_latest_time` |
| Risk confidence was "moderate" for every processed premise, so the indicator never changed | Fitted model: confidence follows the 90% range's spread across bands plus data problems; high, moderate and low all occur | `test_fitted_confidence_tracks_interval_spread` |

## Merged from the teammate's version

A teammate built a separate version of the challenge (single-file app, whole service territory). These ideas were
brought over and rebuilt on this project's network model:

| Idea | What we did | Where | Tests |
|---|---|---|---|
| Logistic risk model, leave-one-storm-out validation, storm-size presets from real storms | Trained on 109 of 110 circuits with this app's own labels and features; added within-storm AUC, a heuristic baseline and recalibration; severity levels now stand for real storms (adds "major") | `pipeline/build_risk_model.py`, `backend/app/risk.py` | `test_fitted_*`, `test_model_card_reports_held_out_storm_validation` |
| Backtest against recorded repair dates | Implied crews for the replay, labelled as a plausibility check | `restoration.backtest` | `test_replay_backtest_reports_implied_crews_on_real_data`, `test_backtest_only_for_replay` |
| Audit-log tab | Server-side, per session, summary-only; new "Audit trail" tab | `backend/app/audit.py`, `AuditCard.tsx` | `tests/test_audit.py` |
| Percentile explanations | Exposure factor says what share of premises in the service area have less | `risk._percentile` | covered by the fitted tests |

What we found while doing it: the teammate's headline AUC (about 0.90; 0.88 here) is mostly storm size. Within a
storm the network features rank premises about as well as the old heuristic (0.63 against 0.62). The fitted model's
real gain is a calibrated level, an honest range and a confidence that varies. The teammate's backtest also fits its
crew count to the observed pace, so it is a plausibility check, and ours is described the same way.

Not brought over, with reasons:

- **Monte Carlo P10/P50/P90 durations.** Its spread comes from an assumed 35% variation per job, which is another
  assumption rather than evidence. The optimistic/conservative bounds stay.
- **Backfeed through open tie switches.** It treats straight-line distance as electrical distance. This app keeps
  "no assumed alternate feeds" until ties can be traced on the network graph.
- **Whole-territory restoration.** The app still processes two circuits; only the risk model uses all of them.
- **Extra declared needs and channels by need.** Already covered: accessibility needs and a voice-channel check for
  hearing or speech needs.

## Known limits (disclosed, not defects)

- **The risk label is a proxy.** It is "damage reached your supply", not a confirmed outage, because the extract has
  no outage records. Within-storm ranking is modest (AUC 0.63), and the recalibration parameters are fitted on the
  same held-out predictions they are evaluated on.
- **Conductor re-stringing has no workbook labor unit.** The prototype fills it with one team assumption (0.3 - 0.8
  direct hours per phase per 100 ft of span, ILM applied once), labelled on every estimate that uses it and
  switchable off. It is not validated against field data. Secondary-line re-stringing stays a lower bound because
  secondary span lengths are not in the data.
- **Critical-facility links are spatial approximations** (nearest transformer within 150 m). Neither processed circuit
  has a hospital within range.
- **Two circuits** are processed; more can be built with `pipeline/build_subset.py --circuits ...`.
- **Greedy scheduling** is a heuristic and not claimed optimal.

## Demonstrated scenario sensitivity

Circuit 18, February 2025 replay (82 repair jobs), four people per crew, 16 working hours per day, no added access
delay:

| Crews | With re-stringing assumption (default): all repairs finished, h | Person-hours, low / high | Workbook data only: modeled work, h | Person-hours, low / high |
|---|---:|---:|---:|---:|
| 1 | 313.43 - 558.31 | 787.0 / 1,420.8 | 253.38 - 386.87 | 642.8 / 959.0 |
| 2 | 154.34 - 278.56 | 787.0 / 1,420.8 | 128.40 - 197.34 | 642.8 / 959.0 |
| 3 | 103.49 - 193.67 | 787.0 / 1,420.8 | 83.50 - 131.05 | 642.8 / 959.0 |
| 6 | 54.22 - 101.36 | 787.0 / 1,420.8 | 40.12 - 74.29 | 642.8 / 959.0 |

With the assumption, all 82 jobs are modeled and the range is a full scenario range that relies on the labelled
assumption. With workbook data only, 46 of the 82 jobs are partly modeled, so those durations cover modeled work only
and the app reports them as lower bounds. In both modes, person-hours stay fixed while the schedule shortens, which
shows crew sensitivity without changing effort.

## Not verified

- **Interactive browser walkthrough.** Headless Chrome screenshots of the four demo deep links render correctly
  (risk card with chance and range, replay with the pace check, neighbouring branch, Circuit 109 operator view).
  Clicking through tabs, keyboard use and screen-reader behaviour have not been checked by a person.
- **Live AI provider.** Integration and mocked-provider tests pass, and the standard-answer fallback works. One call
  with a real key should be made before presenting.
