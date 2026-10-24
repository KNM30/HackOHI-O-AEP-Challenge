# Restoration model (Milestone 3)

Every result is a **simulated model estimate**, not official AEP restoration information.

- **Time reference:** hours elapsed from the start of the simulated storm response (t = 0), not a clock time.
- **Ranges:** an optimistic and a conservative bound built from explicit assumptions. They are scenario bounds, not
  statistical confidence intervals.
- **Validation:** none. Historical ARCOS dates are day-granular and are not used as duration targets.

Code: [`labor_config.py`](../backend/app/labor_config.py) (all assumptions) and
[`restoration.py`](../backend/app/restoration.py). Workbook extract:
`data/processed/labor_reference.json`, built by `pipeline/build_labor.py`. Every value keeps its sheet and cell.

## 1. Damage -> repair job -> tasks -> workbook

- **One job per unique damage location:** a span (by structure), a protective device, or a service transformer.
- **Duplicate records** at one location, such as several replayed reports of the same broken pole, merge into one job.
  Each damage *type* is counted once per job.
- **Damaged line is not treated as a broken pole.** A "line" location maps to a conductor repair; only pole records map
  to pole replacement.
- **Pole plus line at one location:** splices are counted once, under the line repair.

Quantities are given as optimistic / conservative. "Per phase" uses the span's phase count from the primary layer
(`phase_orde`); when it is unknown, the optimistic bound uses 1 phase and the conservative bound uses 3.

| Damage (source) | Job template | Tasks, quantity (opt / cons) | Workbook source | Crew min / useful max |
|---|---|---|---|---|
| Overhead primary line (simulated span, ARCOS `primary`) | Repair damaged overhead line | splice/reconnect 2 / 2 per phase (install only); insulator 0 / 1 per phase (install + removal); **with the re-stringing assumption on (default):** dead-end 0 / 2 per phase (install + removal) and pull/sag 1 per phase at 0.3 / 0.8 h per 100 ft of span | `CNC!B2:C96` connector average; Insulator and Dead-End rows; pull/sag is a **team assumption** (`labor_config.RESTRING`, see [assumptions.md](assumptions.md#conductor-re-stringing-team-assumption-not-aep-data)) | 2 / 4 |
| ARCOS `Pole` | Replace broken pole | pole 1 (install + removal) by height class; crossarm 1 if three-phase; pin and insulator 1 per phase; re-attach conductor 0 / 1 per phase; guy 0 / 1; anchor 0 / 1 (install); grounding 0 / 1 | Pole table C12:D14 (Small 25-35 ft, Medium 40-55 ft, Large 60+ ft; unknown height gives Small..Large); Crossarm, Pin, Insulator, Guying, Anchor, Grounding rows | 3 / 5 |
| ARCOS `Fuse Bank` (damaged device) | Replace fuse cutout | cutout 1 per phase | Fuse Cutout row | 2 / 2 |
| ARCOS `Recloser Bank` | Replace recloser | recloser 1 per phase; equipment lead 1 / 2 per phase | Recloser, Equipment Lead rows | 2 / 3 |
| ARCOS `Switch` | Replace switch | switch 1 | Switch row | 2 / 3 |
| ARCOS `Transformer` | Replace service transformer | transformer 1 by kVA class (unknown kVA gives smallest..largest); equipment lead 1 / 2; cutout 0 / 1 | Transformer table C19:D30 | 2 / 3 |
| ARCOS `secondary` | Repair secondary line | secondary attachment 1 / 2 (install + removal); splice 2 / 4 | Secondary Conductor Attachment row; connector average | 2 / 2 |

### Structure drawings -> components

`structure_drawings.pdf` has 9 image-only pages. Each was read visually, and its AEP distribution-standard (D.S.)
assembly labels are recorded in `labor_config.STRUCTURE_DRAWINGS` (template -> sample structure pages) and
`labor_config.TASK_DRAWINGS` (task -> D.S. assembly and pages). The developer view shows both next to the workbook cell.

| Page | Structure | Assemblies labelled |
|---|---|---|
| 1-2 | Transformer poles | cutout D.S. 61, bracket D.S. 32-E, fuse link D.S. 1001, arrester D.S. 62, transformer D.S. 1000, lead D.S. 75-A, connector D.S. 70, grounding D.S. 65, secondary D.S. 502, risers D.S. 1002 |
| 3 | Single-phase dead-end | primary dead-end D.S. 31, guying D.S. 400, neutral dead-end D.S. 501-B, connector D.S. 70 |
| 4 | Single-phase tap / corner | primary dead-end D.S. 31, guying D.S. 400, grounding D.S. 65, connectors D.S. 70 / 74 |
| 5 | Single-phase tangent | pin & insulator D.S. 30, wire tie D.S. 40, neutral D.S. 500 |
| 6-7 | Three-phase taps | pin & insulator D.S. 30, ties D.S. 40, dead-end D.S. 31, guying D.S. 400, bracket D.S. 32-D, connectors |
| 8 | Three-phase dead-end | crossarm D.S. 20, dead-end D.S. 31, guying D.S. 400, neutral dead-end D.S. 501-B |
| 9 | Three-phase tangent | pin insulator D.S. 30-A, pins D.S. 30-B, fiberglass crossarm D.S. 26, wire tie D.S. 40 |

How the drawings shape the templates: a crossarm is counted only for three-phase spans (p. 9 vs the single-phase
pole-top pin on p. 5); pin, insulator and tie quantities scale with phases; guy and anchor are conservative-only because
they appear on dead-end and tap structures (pp. 3, 4, 6-8) but not on tangents. Reclosers and switches are not in the
sample drawings and are marked as such. The drawings show components, not quantities per job, so the quantities remain
labelled assumptions.

Rules applied throughout:

- **Removal hours** come from the workbook's removal column and are used only when a part is physically removed. They
  are never assumed equal to install hours.
- **Missing workbook values** make the job *unsupported*, with a message. They are never treated as zero.
- **Partly covered repairs** are labelled. The workbook has no labor unit for re-stringing conductor along a span.
  With the re-stringing assumption on (default), overhead line repairs add the assumed pull/sag time and become fully
  modeled, labelled as relying on a team assumption, and the card also shows the workbook-only lower bound. With it
  off, line repairs count splices and re-attachment only and are lower bounds. Secondary repairs always count
  attachments and splices only, because secondary span lengths are not in the data.

### Unsupported damage (explicit incomplete estimate)

- **Underground primary cable.** There is no underground cable, splice or termination labor in the workbook, and
  excavation is priced per cubic foot with no volume available.
- **Spans with unknown mounting**, such as proximity-bridged gaps.
- **Lights and capacitor banks** are excluded from scenarios.

A premise whose restoration depends on an unsupported job gets **"Insufficient information"** with no range. The
overall completion time is then shown as "at least".

## 2. Labor conversion

**Direct labor** = Σ (unit hours × quantity) + adders.

- Adders are added only when the record reports an access issue:
  - "Restricted Access Work" (0.5 h, `Labor only work!D2`), or
  - "Confined Property Access" (0.5 h, `D3`) when the special equipment is a backyard bucket.
- At most one access adder is applied per job.
- Not applied, with reasons:
  - Excavation (per cubic foot, no volume available).
  - Junction pole (no value in the workbook).
  - "Access Constraint Adder" (duplicates Restricted Access Work).

**Total person-hours** = direct labor × **4.5** (`Indirect Labor Multiplier!B1`).

- The multiplier is applied **once per job**.
- It covers drive time, safety briefings and setup, so no separate travel or setup time is added.
- Tests check that person-hours = direct × 4.5 exactly, and that crew or delay inputs never change effort.

**Unit interpretation (demo assumption): `LABOR_HOURS_BASIS = "person_hours"`.** The workbook does not say whether its
hours are per person or per crew.

- **Person-hours** (the default) follows the challenge guidance "ILM × direct labor = total person-hours". A crew of
  *N* works a job in person-hours / min(*N*, the job's useful crew size).
- **If the hours were per crew** (`"crew_hours"`), adding people would not shorten jobs, and total effort would be *N*
  times higher.

The UI shows this as a warning on every result.

## 3. Waiting delays (elapsed time, never multiplied)

These delay when a job can start. A crew can work on other jobs while one job waits.

| Wait | Optimistic / conservative (h) | Applies to |
|---|---|---|
| Damage assessment / patrol | 1 / 3 | all jobs and all isolation switching |
| Weather hold | 0 / 2 | all jobs |
| Material staging | 0 / 4 | pole, transformer, recloser and switch jobs |
| Access delay (user input, 0-48) | as entered | jobs with a reported access issue, or every job if selected |
| Manual switching per switch | 0.5 / 1.5 | isolation, one responder, done in sequence |
| Re-energization | 0.25 / 0.5 | after isolation or after the last blocking repair |

## 4. Scheduler

- **Crews:** 1-20 crews of 2-8 people. **One crew works one job at a time.**
  - People beyond a job's useful maximum do not speed it up.
  - Crews smaller than a job's minimum cannot take it. For example, pole setting needs 3 or more people; such a job is
    reported as "needs a larger crew" and any customer depending on it gets no range.
- **Working hours:** crews work 8-16 hours per day in daily windows starting at t = 0. An unfinished job continues in
  the next window.
- **Rule:** greedy list scheduling. When a crew is free, it takes a ready job in this order:
  1. **Critical facilities first** (scenario input, on by default): a job that a hospital, fire station or ambulance
     station is waiting on.
  2. Then the job that unblocks the most waiting customers per hour of crew work.
  3. Ties break on job ID, so results are deterministic.

  This is a heuristic and is **not claimed to be optimal**. Priority applies among jobs that are ready to start; a
  facility job still waiting for materials does not hold a free crew idle.
- **Critical facilities** (guide section 4):
  - The public hospital, fire-station and ambulance layers have no electrical relationship, so the pipeline
    (`pipeline/critical.py`) links each facility to the nearest service transformer within **150 m**. This is a
    labelled approximation; facilities farther away stay unlinked.
  - A facility depends on exactly what that transformer's premises depend on.
  - Only the facility **type** and its simulated outcome reach the browser: never its name, address, coordinates or
    linked equipment.
  - CIR18 has **no** facility within 3 km. CIR109 links an ambulance station (12.6 m) and a fire station (29 m), so it
    is built as the second circuit.
  - **Observed on the real data:** in the customer scenarios and the Feb 2025 replay on CIR109, the facilities' repairs
    are also the repairs that restore the most customers (their shared fuse serves 541 premises), so the order is the
    same with priority on or off. Every result now says which case applies (`restoration.critical_priority`):
    `changed_order` (with the hours gained), `already_first`, or `no_facility_waiting`.
  - **Operator-view scenario `critical_facility`** (CIR109 only): one overhead span on a facility's own supply path
    (about 10 customers wait on it) and one span on a larger branch that does not feed any facility (about 1,100
    customers, at least 4x as many). With 1 crew, ranking by customers alone repairs the larger branch first; with
    priority on, the fire station comes back about 1.5 h sooner (3.6 - 11 h vs 5.1 - 14 h; workbook data only, at
    least 2.7 h vs at least 4.2 h). The locations are chosen
    automatically by `scenarios.critical_scenario` and are the same for every premise. Covered by
    `test_circuit_109_priority_changes_order_on_real_data`. Because the facility span sits next to the facility, its
    locations carry no coordinates and the map shows no transformer impacts while it is active, whatever scenario id
    a request uses (`test_operator_view_never_locates_the_facility`).
- **Crews needed for 2 days / 3 days / 1 week** (guide section 5): for the active scenario, the fewest crews (1-20, other
  crew inputs unchanged) whose schedule finishes all modeled work within each time, under both bounds. When any job is
  partly modeled or cannot be scheduled, the numbers are labelled as minimums.
- **Known heuristic artifact:** like any greedy list scheduler, a change that delays some jobs can reorder the queue
  and occasionally shift the *overall* completion slightly in a counter-intuitive direction. For example, on the Feb
  2025 replay with 3 crews, a 12 h delay on the reported-access jobs moves the optimistic overall end from 83.5 h to
  83.3 h. Per-customer ranges that depend on the delayed jobs still move later as expected.
- **Dependencies:**
  - Repairs have no prerequisites on each other: de-energized sections can be worked in parallel.
  - Upstream position matters only for **re-energization**. A customer is restored after the *last* repair on their
    path, or after isolation.
  - No individual customer is prioritized from source medical flags (`critical_c` is never used).

## 5. Customer range vs whole scenario

- **Fixed scenario.** The simulation endpoint takes a set of damage locations and resolves them through one
  circuit-wide index. The job set, the effort and the schedule are therefore identical for every premise evaluated
  against the same request. The UI pins the active scenario while you select other premises.
- **Repair-dependent (or unresolved) premise:**
  - Range = the latest scheduled end among its blocking repairs, plus re-energization, under each bound.
  - If it is also isolatable from other faults, switching time is included.
  - Unresolved premises are labelled "repair-based; field sectionalizing not assumed".
- **Isolation candidate:** two alternative outcomes, not one interval.
  - If isolated: assessment + switching for each distinct mapped switch + re-energization.
  - Otherwise: the repair-based range, because a mapped switch alone does not justify a short promise. When that
    repair is only partly modeled, only "at least" its optimistic end is shown; guidance, alerts and the assistant
    treat its length as open-ended.
  - Any fault on the premise's own path makes it repair-dependent.
- **Whole scenario:** reported separately from the selected customer's range, with total labor effort
  (person-hours) shown apart from elapsed duration.
  - `complete` is true only when every job is scheduled **and fully modeled**.
  - Otherwise only "at least" the optimistic end is reported, with the number of partly modeled jobs. The Feb 2025
    replay on CIR18 has 46 of 82 jobs partly modeled with the re-stringing assumption off, so it then reports "at
    least" only; with it on (default), all 82 are modeled and it reports a full range. The end of the modeled work is
    kept for developers as `modeled_work_upper_h`.

## 6. Protection review relevant to timing

- **Sectionalizers** do not interrupt fault current. They count the operations of an upstream recloser and open while
  it is open.
  - A sectionalizer is used as the sustained-outage boundary only if an evidenced recloser sits above it. Otherwise the
    walk continues upward.
  - CIR18 has none, but the rule is covered by a test.
- **Mapped protective devices missing from every upstream chain** are skipped (11 on CIR18). This is an approximation,
  not proof that the next device up is physically correct. Any job whose fault walk passed over such a device is marked
  `protection_uncertain`, a warning is shown, and the premise's confidence is lowered.
