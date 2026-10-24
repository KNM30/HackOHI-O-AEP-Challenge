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
production outage system, so a two-circuit subset, uncalibrated risk bands, and approximate secondary attribution are
disclosed design limits, not gaps.

## Verification performed

| Check | Result |
|---|---|
| Backend tests | **136 passed** (`..\.venv\Scripts\python -m pytest -q` from `backend`) |
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
| ARCOS damage | Matched to the nearest asset of the right type (capped distance); historical-event risk signal; storm replay scenario | `pipeline/matching.py`, `backend/app/risk.py`, `backend/app/scenarios.py` |
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
| 1. Produce a risk estimate or clearly defined band | Meets | Low / moderate / high bands from a documented heuristic; explicitly not a probability ([risk_model.md](risk_model.md)) |
| 1. Use historical, asset, network, spatial or storm signals | Meets | Interrupting overhead exposure, distinct historical events, service-drop type, severity input |
| 1. Show factors and uncertainty | Meets | Factor list with points; separate confidence with reasons; "high" confidence never offered |
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
| 5. No raw personal data, employee contacts, precise sensitive locations or internal fields | Meets tested scope | Response schemas are an allowlist; hashed IDs; rounded damage points; facility type only; privacy tests pass. Not a penetration test |
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

## Known limits (disclosed, not defects)

- **Risk bands are a heuristic**, not a calibrated probability; there are no outage-labelled records to validate
  against. On Circuit 18 every premise has the same two historical events, and at "severe" all 893 premises are high
  because they share 3.5 km of breaker-only overhead line. At "moderate", bands do differ (for example `PRM-00340340`
  moderate, `PRM-00770FFC` high).
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

- **Browser walkthrough.** The full visual journey, keyboard use and screen-reader behaviour have not been checked in
  a browser. The build passes and the API behind each card is tested.
- **Live AI provider.** Integration and mocked-provider tests pass, and the standard-answer fallback works. One call
  with a real key should be made before presenting.
