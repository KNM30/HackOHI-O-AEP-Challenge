# Assumptions and decisions

This log records modelling and data decisions. Numbers come from `docs/data_inspection_report.md` (regenerate with
`pipeline/inspect_data.py`).

## Data scope

- **Demo subset: Circuit 18 (`0000018` / `CIR18`).** It has 893 premises, 292 service transformers, 77 protective
  devices and 118 ARCOS damage records, most from the 13-17 Feb 2025 event. Every premise is on one oriented network,
  and all 1,563 upstream-chain ancestry checks pass. Other circuits can be built, but some orient less cleanly (CIR72:
  77% chain consistency) or cannot be oriented yet (CIR10, CIR2).
- Source data in `challenge_repo/` is never modified. Archives are extracted per archive, so shapefile companion files
  stay together.
- CRS: distances use EPSG:32617 (UTM 17N), and display uses EPSG:4326. Point Z values are dropped.

## Identifiers and joins

- Premise to equipment uses `matched_upstream.txt`, the direct relationship file. Each premise row lists elements
  nearest-first: service transformer, then fuses, reclosers, sectionalizers and step transformers, then the circuit
  breaker. The element feature IDs match the layer `id` values: 100% for transformers and 94% for isolating devices.
- `Customer.aep_xfmr_l` agrees with the upstream file's nearest transformer for 99.97% of premises. The upstream file
  wins when they differ, and the difference is flagged.
- ARCOS circuit labels (`CIR18`) map to GIS `circuit_id` (`0000018`) through `Primary.aep_circui`.

## Network topology (approximation, labelled)

- Nodes are structure location numbers. Segment ends are snapped to pole and device points within **3 m**.
- Pieces of a circuit separated by digitising gaps of **10 m or less** are joined with flagged `spatial_gap` edges.
  CIR18 needs 3 of these. Pieces farther apart are not joined by proximity.
- The feeder head (root) is not in the data. It is chosen as the leaf whose orientation agrees best with the supplied
  `upstream_l` device hierarchy. For CIR18, all 149 pairs agree.
- A device located at a junction pole can protect only some of the branches leaving that pole (for example, a tap fuse
  where the main line continues). Its covered branches are those containing transformers whose premises list that
  device in the upstream file. When no such evidence exists, all branches are assumed and flagged
  (`all_children_assumed`: 18 of 77 CIR18 devices).
- **Fault clearing:** damage at a structure, or on the span into it, is cleared by the nearest upstream *protective*
  device that covers that span, or by the substation breaker if there is none.
  - Protective devices are fuses, reclosers and sectionalizers. Manual switches never clear faults; they only isolate.
  - Protective devices that appear in **no premise's upstream chain** are skipped (11 on CIR18, including two reclosers
    that exist in GIS). The upstream file is the authoritative dependency source, and using these devices would give a
    fault an empty interruption zone.
  - A damaged fuse or recloser opens its own zone. Transformer and secondary damage affects only that transformer's
    premises.

## Damage scenarios and step restoration (Milestone 2)

- Scenario damage is separate from historical records.
  - Scenarios are premise-relative and deterministic: shared upstream line, local branch, neighbouring branch, and
    multiple locations.
  - Historical records enter a scenario only through the explicitly labelled *Replay the Feb 2025 storm damage
    (simulation)*.
  - Location IDs are salted hashes. Labels use bucketed counts and distances.
- **Initial interruption:** every premise whose upstream chain contains the device that would open. A damaged
  transformer or protective device interrupts its own customers.
- **After isolation**, each interrupted premise is classified as:
  - *Waits for repair*: the damage is on its own supply path, or on its own transformer or a protective device it
    depends on.
  - *Possible earlier restoration*: the damage is elsewhere, and a mapped, normally closed switch on a known branch
    (evidenced coverage, or a single outgoing span) lies between the damage and the premise's branch point. Opening it
    and re-closing the tripped device would leave the premise a supply path with no damage on it.
  - *Unresolved*: the damage is elsewhere, but no such switch is mapped. Field sectionalizing might help, but the model
    does not assume it.
  - When several damages apply, the worst status wins.
- Not assumed:
  - alternate feeds or ties to other circuits
  - remote or automatic switching
  - automatic re-energization
  - that geographic proximity means electrical dependency (a nearby but unrelated damage location is called out
    explicitly)
- These are simplified restoration possibilities, not field switching instructions or confirmed utility actions.
- On CIR18, only five switches have a known branch, so most "elsewhere" cases are unresolved. That is a property of the
  mapped data, not a statement about real crews.

## Damage matching

- ARCOS points are already snapped onto assets: the median distance is 0 m for every point-asset type.
- Each record is matched only to assets of its own type, within **15 m**. It is matched first among assets on its
  ARCOS-labelled circuit, because shared structures tie at 0 m across circuits. Only if that fails is it matched among
  all circuits, and then it is flagged `label_fallback`.
- Secondary-wire damage goes to the nearest service transformer within **60 m**. This is coarser and is labelled
  `secondary->nearest_transformer`.
- Lights and capacitor banks are not modelled. Records beyond the cap stay unmatched.
- Report and repair fields are date-only. Twenty-four records carry a 2025-10-24 repair date that looks like a
  placeholder. Durations are therefore not used as hour-level restoration targets.
- `Media` is undocumented, so it is not used.
- ARCOS has no customer-outage counts, so historical records describe *damage*, not confirmed outages.

## Privacy

See README, Privacy section, and section 7 of the inspection report.

## Restoration (Milestone 3)

See [restoration_model.md](restoration_model.md) for the damage-to-task mapping, labor conversion, waiting delays,
scheduler rules and customer ranges. Protection review notes:

- Sectionalizers only bound an outage when an evidenced recloser sits above them.
- Skipping unevidenced devices is an approximation. It is flagged per job (`protection_uncertain`) and lowers
  confidence.

## Labor workbook (reviewed before M3; corrected)

The earlier version of this section said the 4.5 multiplier applies to "direct CU hours plus adders" without
separating labor effort from waiting time. This corrected version replaces it.

**What the workbook states (verified cell by cell):**

- `CNC` sheet: `INSTALL_HOURS` and `REMOVE_HOURS` per connector CU code. Its note says the average "includes all
  connector CU sizes and valid zero-hour records".
- `Labor time material related`: category **averages** of install and remove hours per CU. The categories are
  crossarm, bracket, pole by size group, transformer by kVA (with CU counts), anchor, equipment lead, grounding,
  guying, dead-end, insulator, pin, recloser, secondary attachment, service, switch and fuse cutout.
- `Labor only work`: rows described as "*additional labor required* when ...", that is, extra work effort.
  - Restricted access, confined property access, remote site access, the access constraint adder, specialized
    handling and site complexity are each 0.5 h.
  - The remote location adder is 1.312 h, and structural realignment is 0.544 h.
  - Manual excavation (1.5 h) and difficult excavation (4 h) are **per cubic foot**.
  - "Complex Work Location" (junction pole) has **no value**.
- `Indirect Labor Multiplier`: ILM = 4.5. Its note says it "should be multiplied times any labor hours to take into
  account drive time, safety discussion time, set up time, etc."

**How M3 will use it:**

1. **Eligible direct labor** = Σ (CU install + remove hours × quantity) + the applicable "additional labor" adders.
   The adders are work effort, so they are eligible.
2. **Total person-hours** = eligible direct labor × 4.5, applied **once**. Drive, safety-briefing and setup time are
   inside the ILM, so no separate per-job travel or setup is added.
3. **Elapsed waiting delays** are calendar time and are **never multiplied by 4.5**. Examples: a blocked road, waiting
   for tree clearing or safe conditions, waiting for materials, or crew mobilization. They are added *after* converting
   person-hours to working time.
4. Working time = total person-hours / crew size. It is not divided again by a productivity factor, because the ILM
   already accounts for non-productive time. Workday length and crew availability turn working time into calendar
   time.

**Ambiguities, documented rather than resolved silently:**

- The workbook does not say whether the hours are per person or per crew. Following the challenge guidance (ILM ×
  direct labor = total *person*-hours), they are treated as person-hours.
- Some rows overlap: for example, "Restricted Access Work" and "Access Constraint Adder" are both 0.5 h for similar
  conditions. Only one adder per access condition will be applied, to avoid double counting.
- Excavation adders need an assumed volume in cubic feet. They will be exposed as an explicit scenario assumption or
  left out.
- The junction-pole adder has no hours and will not be used.
- **There is no labor unit for replacing or re-stringing primary conductor**, in any sheet or per length. This is
  filled by one labelled team assumption (next section), not by inventing workbook rows.

## Conductor re-stringing (team assumption, not AEP data)

Most simulated damage is a damaged span of overhead line, and the workbook can price only its splices and insulators.
Without a rate for replacing the wire, every such repair could only be a lower bound. The brief asks for a credible
range and for transparent assumptions, so the prototype fills this one gap explicitly:

- **Dead-ending the new conductor at both structures:** workbook Dead-End row (install + removal), 0 per phase
  (optimistic: re-tied on tangent structures, already covered by splices) to 2 per phase (conservative).
- **Pulling, sagging and tying in the new conductor:** **0.3 - 0.8 direct hours per phase per 100 ft** of the damaged
  span. The span length comes from the GIS primary layer (capped at 500 ft). This is the only invented number. It is
  treated as direct labor, so the 4.5 ILM applies once, like every other task.
- **Scale check:** a median 205 ft single-phase span gives 0.6 - 1.6 direct hours, similar to setting a small pole
  (about 1.9 workbook hours). A single damaged span on Circuit 18 comes out at about 2.5 - 8.4 h with the default
  crews.
- **Labelled everywhere:** the card, alert text, confidence (-10), "why" list and developer view (`source: team
  assumption ...`) all say the time includes this assumption. The card also shows the estimate from AEP's labor data
  alone ("at least ...").
- **Switchable:** the scenario input "Include our assumed time for replacing damaged wire" (`restring_assumption`,
  deep link `restring=off`) restores the workbook-only lower bounds.
- **Not covered:** secondary-line re-stringing (no span length in the data) stays a labelled lower bound.

The rate lives in `labor_config.RESTRING`; changing it there changes every estimate.
- Category averages hide size variation (except transformers by kVA and poles by height). Ranges in M3 will reflect
  this rather than present single values.

## Pre-storm risk model (M6)

Details and validation tables are in [risk_model.md](risk_model.md).

- **Label is a proxy.** "Hit" means at least one ARCOS damage record from that storm would have interrupted the premise
  under the app's protection model. The extract has no customer-outage records.
- **Storms** are territory-wide groups of report dates within 2 days; only the 11 with at least 10 records train the
  model. Severity scenarios stand for real storm sizes (15, 46, 194, 1,254 records).
- **Training scope:** all circuits except circuit 70, which fails in the circuit builder. Two circuits are still
  processed for the app; the model only needs per-premise features, which are computed by the same code at request
  time.
- **Recalibration** (two parameters, fitted on the held-out predictions) corrects over-prediction above about 10%. The
  recalibrated calibration table is in-sample for those two parameters.
- **Bands** on the chance: low under 5%, moderate 5% to 15%, high 15% or more. The pre-storm alert still needs
  the high band (15% or more). With probability bands that is stricter than before: in a major storm only 10 of 893
  Circuit 18 premises qualify, and in a severe storm 410. Lowering it to "moderate" (5%) is a one-line change in
  `alert_config.PRE_STORM_MIN_BAND`.
- **Heuristic fallback** stays in the code for when `risk_model.json` is missing, and is the baseline in the
  validation.

## Audit trail (M6)

- The backend keeps the last 2,000 decisions (risk, simulation, briefing, assistant) in memory, keyed by a random
  per-page session id sent as `X-Session-Id`. Entries hold hashed IDs, inputs, an output summary and the model build.
  For assistant questions only the length and classified topic are stored, never the text.
- It is lost on restart and is not a compliance log. A production system would need durable, access-controlled
  storage.
