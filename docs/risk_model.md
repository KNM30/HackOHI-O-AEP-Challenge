# Pre-storm risk model (Milestone 2)

The pre-storm risk is a deterministic heuristic that ranks premises into bands. **It is not a probability** and has
not been calibrated, because the data contains no confirmed customer-outage records to validate against. All weights
and thresholds are in [`backend/app/risk_config.py`](../backend/app/risk_config.py). The scoring code is
[`backend/app/risk.py`](../backend/app/risk.py).

## Features

| Feature | Definition | Unit | Normalisation | Max points |
|---|---|---|---|---|
| Interrupting overhead exposure | Overhead primary length whose damage would trip a protective device in the premise's upstream chain, or the breaker. It is the sum of the spans each of those devices clears directly, so it includes the premise's own supply path. | km | linear, saturating at 15 km | 50 |
| Historical storm events | Distinct dated events (records within 2 days are grouped) in which at least one ARCOS record would have interrupted the premise under the protection model. | count | linear, saturating at 3 | 30 |
| Service drop | Customer-layer `kind_of_se` | category | Overhead 10, Underground 0, Unknown 5 | 10 |
| Storm severity (scenario input) | Chosen by the user: minor / moderate / severe. **Not a forecast.** | factor | 0.6 / 1.0 / 1.5 | multiplier |

The score is (exposure + history + service) × severity factor, capped at 100.

The bands are **low** below 25, **moderate** from 25 to below 45, and **high** at 45 or more. A result within 4 points
of a band edge is flagged as borderline.

### Why these features, and what was left out

- **Double counting.** Supply-path overhead length is *contained in* the interrupting exposure, so it is reported but
  not scored separately. Historical records from the same storm count once, as one event. History and exposure are
  still correlated (more exposed line attracts more damage records), so history has the smaller weight and is capped.
- **Underground line** is shown but not scored as storm exposure.
- **Not used:**
  - Vegetation and asset condition are not in the data.
  - Pole install years exist, but nothing in the extract links them to damage, so they are not scored.
  - ARCOS `Media` is undocumented.
  - There is no live weather.
- **Saturation length.** 15 km is set just above the CIR18 maximum (13.3 km), so no premise is clipped. Revisit it if
  other circuits are added.

## Behaviour on CIR18 (893 premises)

| Severity | low | moderate | high |
|---|---|---|---|
| minor | 505 | 381 | 7 |
| moderate | 0 | 531 | 362 |
| severe | 0 | 0 | 893 |

- Every CIR18 premise depends on 3.5 km of overhead line that only the substation breaker protects. That sets a
  floor, which is why the severe scenario puts the whole circuit in the high band.
- History currently gives every premise the same 2 events. Breaker-level damage reached everyone in the Feb 2025
  storm and on 2024-01-10, so history does not separate CIR18 premises.
- Premises with identical features get identical results. The model does not create differences between them.

## Confidence (separate from the band)

Confidence starts at 100 and loses points for specific evidence problems. **Moderate** means 55 or more; **low** means
below 55. **High is never offered**, because passing the chain-consistency checks does not prove the inferred network
is physically correct, and there is no outage-labelled data.

| Deduction | Points |
|---|---|
| No outage-labelled validation (always applies) | -25 |
| Feeder head is inferred (always applies) | -10 |
| Proximity-bridged gap on the supply path | -5 each, up to 2 |
| A device in the chain has assumed branch coverage | -10 |
| More than 5% of the interrupting length has unknown mounting | -10 |
| Some of the premise's historical evidence uses approximate matches (label fallback, secondary to transformer, or more than 5 m) | -5 |
| Circuit root consistency below 0.95 | -10 |
| Circuit chain consistency below 0.95 | -20 |
| Each premise data flag | -25 |
| Unknown service type | -5 |

## Fallback

If the premise's transformer is not on the oriented network, or the premise is missing from the upstream file, the API
returns `status: insufficient_data` with no band and no score. It says which inputs are missing and suggests
general storm preparation.

## Separation from simulated outages

`/api/premises/{id}/risk` depends only on the premise and the severity input. Running a damage scenario never changes
it, and the UI shows the two in separate, labelled cards.
