# Pre-storm risk model

The pre-storm risk is a **logistic model fitted on every circuit in the service area and validated by leaving out
whole storms**. It gives a recalibrated chance that storm damage cuts a premise's supply, with a 90% range, a band and
a separate confidence level. The training script is [`pipeline/build_risk_model.py`](../pipeline/build_risk_model.py),
which writes `data/processed/risk_model.json`. Scoring is in [`backend/app/risk.py`](../backend/app/risk.py), and
settings are in [`backend/app/risk_config.py`](../backend/app/risk_config.py).

The approach comes from a teammate's version of this challenge (logistic regression, leave-one-storm-out validation,
storm-size presets tied to real storms). We rebuilt it on this project's own network model and added a within-storm
evaluation, recalibration and a comparison with the earlier heuristic (see [What we learned](#what-we-learned)).

If `risk_model.json` is missing, the app falls back to the earlier heuristic band, described at the
[end of this page](#fallback-heuristic-band).

## What the model predicts (the label)

Each row is one premise in one past storm. A premise is **hit** when at least one ARCOS damage record from that storm
would have interrupted it under the app's protection model: the record's protective device is in the premise's
upstream chain, or the record sits on its supply path. This is the same rule as `CircuitNetwork.relation()`, so
training and the live app agree.

**This is a damage-based proxy for an outage, not a confirmed outage.** ARCOS records damage, and the extract has no
customer-outage records. The customer-facing text says "chance that storm damage cuts your supply", not "chance of an
outage".

Storms are the territory-wide groups of report dates within 2 days of each other. The 11 storms with at least 10
records are used. That gives 99,857 premises on 109 of 110 circuits (circuit 70 fails in the circuit builder with an index error and is left out)
and about 1.1 million premise-storm rows.

## Features

| Feature | Definition | Standardised coefficient |
|---|---|---:|
| Storm size | log of territory-wide ARCOS records in the storm. In the app this is the severity scenario. | 1.33 |
| Interrupting overhead line | log(1 + km of overhead primary whose damage would trip a device the premise depends on) | 0.08 |
| Past storms | Share of the *other* training storms that hit the premise (the held-out storm is never counted) | 0.11 |
| Protective devices on the path | Number of fuses, reclosers and sectionalizers between the premise and the substation | 0.50 |
| Overhead service drop | 1 overhead, 0 underground, 0.5 unknown | 0.09 |

All signs are positive. Pole install year is not used: the teammate's version tested it and found no gain.

## Severity scenarios

Severity is a scenario input, not a forecast. Each level stands for a real storm's size:

| Severity | Storm size (records) | Like |
|---|---:|---|
| minor | 15 | a typical small storm |
| moderate | 46 | January 2025 |
| major | 194 | late September 2024 (Helene's remnants) |
| severe | 1,254 | February 2025, the largest in the data |

## Validation (leave one storm out)

For each storm, the model is fitted on the other 10 and scored on the held-out one. The history feature for the
held-out storm uses only the training storms.

| Metric | Fitted model | Earlier heuristic |
|---|---:|---:|
| AUC, all held-out rows pooled | 0.878 | n/a |
| AUC within a storm, mean of 11 storms | 0.628 | 0.618 |

**The pooled AUC is high mainly because storm size is known in advance:** big storms hit far more premises.
Ranking premises *within* one storm is modest, and only slightly better than the heuristic. Brier scores are almost
the same as a storm-size-only model. So storm size sets the level, and network position moves it up or down a little.
The app says this in the "How the model was checked" panel.

Per held-out storm (predicted = recalibrated mean chance):

| Storm | Records | Observed share hit | Predicted | AUC within storm | Heuristic AUC |
|---|---:|---:|---:|---:|---:|
| 2023-10-21..2023-10-23 | 16 | 0.0% | 0.8% | 0.61 | 0.46 |
| 2024-01-10 | 11 | 1.0% | 0.5% | 0.33 | 0.63 |
| 2024-04-12 | 17 | 0.8% | 0.7% | 0.51 | 0.43 |
| 2024-05-27 | 13 | 0.3% | 0.6% | 0.68 | 0.44 |
| 2024-08-09 | 11 | 0.2% | 0.6% | 0.84 | 0.89 |
| 2024-09-26..2024-10-02 | 194 | 5.1% | 4.4% | 0.60 | 0.58 |
| 2024-11-21..2024-11-23 | 15 | 0.5% | 0.7% | 0.57 | 0.57 |
| 2025-01-06..2025-01-07 | 46 | 3.2% | 1.3% | 0.61 | 0.61 |
| 2025-02-12..2025-02-18 | 1,254 | 19.1% | 19.7% | 0.65 | 0.59 |
| 2025-05-31 | 11 | 0.1% | 0.6% | 0.80 | 0.76 |
| 2025-12-19 | 10 | 0.2% | 0.5% | 0.69 | 0.85 |

### Recalibration

The raw model over-predicted above about 10%, mostly because of the largest storm (27% predicted, 19% observed). A
two-parameter recalibration, logit(p) = a + b * logit(raw), is fitted on the held-out predictions (a = -0.57,
b = 0.86). It changes the level, not the ranking. Because the two parameters are fitted on the same held-out
predictions, the table below is in-sample for them:

| Predicted range | Premise-storms | Mean predicted | Observed |
|---|---:|---:|---:|
| 0-2% | 880,042 | 0.7% | 0.7% |
| 2-5% | 91,133 | 3.2% | 4.0% |
| 5-10% | 24,286 | 6.6% | 6.8% |
| 10-20% | 65,319 | 16.2% | 14.1% |
| 20-30% | 31,603 | 23.4% | 25.4% |
| 30-45% | 5,699 | 34.2% | 36.6% |
| 45-60% | 345 | 47.9% | 17.7% |

The last bin is small and still over-predicts. Few premises reach it, and their 90% range is wide.

## 90% range

The range combines the coefficients' uncertainty (inverse Hessian) with storm-to-storm variation the features cannot
explain. That variation is the RMS logit gap between observed and predicted share hit in each held-out storm,
weighted toward larger storms (sigma = 0.87). It dominates the range: storms of the same size have hit very different
areas. Premises within a circuit are correlated, so the coefficient part alone would be too narrow; the storm term
is what keeps the range honest.

## Bands

On the recalibrated chance: **low** under 5%, **moderate** 5% to under 15%, **high** 15% or more. 5% is about 1 in 20.
15% is below the 19% of premises the largest storm on record reached. A chance within 20% (relative) of a band edge is
flagged as borderline. The pre-storm alert needs the high band
([alerts_and_guidance.md](alerts_and_guidance.md)).

| Severity | Circuit 18 (893): low / moderate / high | Circuit 109 (1,806): low / moderate / high |
|---|---|---|
| minor | 893 / 0 / 0 | 1,806 / 0 / 0 |
| moderate | 883 / 10 / 0 | 1,806 / 0 / 0 |
| major | 562 / 321 / 10 | 1,478 / 328 / 0 |
| severe | 0 / 483 / 410 | 0 / 581 / 1,225 |

## Factor explanations

Each network factor shows how far it moves the premise's chance, in percentage points, against an average premise
(that feature at the service-area mean, everything else unchanged). The exposure factor also says what share of
premises in the service area have less interrupting overhead line. Storm size is shown as the scenario input and
named as the strongest factor.

## Confidence (separate from the band)

Confidence starts at 100. The 90% range replaces the old "no validation" deduction:

| Deduction | Points |
|---|---|
| 90% range stays within one band | 0 |
| 90% range spans two bands | -30 |
| 90% range spans all three bands | -60 |
| Feeder head is inferred (always applies) | -10 |
| Proximity-bridged gap on the supply path | -5 each, up to 2 |
| A device in the chain has assumed branch coverage | -10 |
| More than 5% of the interrupting length has unknown mounting | -10 |
| Some historical evidence uses approximate matches | -5 |
| Circuit root consistency below 0.95 | -10 |
| Circuit chain consistency below 0.95 | -20 |
| Each premise data flag | -25 |
| Unknown service type | -5 |

**High** is 80 or more, **moderate** 50 or more, **low** below 50. Confidence now varies: a premise in a small storm
usually has a narrow range inside the low band (high confidence), while the same premise in a major storm can span
all three bands (low confidence).

## What we learned

- The teammate's headline (pooled AUC about 0.90) reproduces here (0.88), but it mostly measures storm size. Within
  a storm, the network features rank premises only slightly better than our earlier hand-weighted score
  (0.63 against 0.62).
- What the fitted model adds is a *level* that matches history (after recalibration), an honest range, and a
  confidence that responds to that range. Those are what the brief asks for: "a risk band and confidence level that
  are easy to understand" and "communicate uncertainty".
- Better within-storm ranking would need data this extract lacks: vegetation, tree cover, wind exposure and
  equipment condition.

## Fallback

If the premise's transformer is not on the oriented network, or the premise is missing from the upstream file, the API
returns `status: insufficient_data` with no band and no chance. It says which inputs are missing and suggests general
storm preparation.

## Separation from simulated outages

`/api/premises/{id}/risk` depends only on the premise and the severity input. Running a damage scenario never changes
it, and the UI shows the two in separate, labelled cards.

## Fallback heuristic band

Used only when `risk_model.json` has not been built (`method: "heuristic"`). The score is
(exposure + history + service points) x severity factor, capped at 100. It is not a probability.

| Feature | Definition | Max points |
|---|---|---:|
| Interrupting overhead exposure | Overhead primary length whose damage would trip a device the premise depends on; linear up to 15 km | 50 |
| Historical storm events | Distinct events (records within 2 days grouped) that would have interrupted the premise; linear up to 3 | 30 |
| Service drop | Overhead 10, Underground 0, Unknown 5 | 10 |
| Storm severity | minor 0.6, moderate 1.0, major 1.25, severe 1.5 | multiplier |

Bands: low below 25, moderate 25 to below 45, high 45 or more. Confidence uses the deductions above, with a fixed
-25 for "no validation" instead of the range deduction, and is never high.
