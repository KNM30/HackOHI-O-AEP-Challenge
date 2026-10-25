"""All risk-scoring weights, normalisation constants and thresholds (single source).

Documented in docs/risk_model.md. Changing a value here changes the model; the
tests check monotonicity and band boundaries, not specific premises.
"""

# Simulated storm severity: a scenario input chosen by the user, NOT a forecast.
# The factor scales the susceptibility points; factors are increasing so higher
# severity can never lower the score.
# "factor" drives the fallback heuristic; "storm_size" (territory-wide ARCOS damage records)
# drives the fitted model. Sizes come from a real past storm ("analog_event", read from
# risk_model.json) except "minor", which uses the typical size of the small storms.
SEVERITY = {
    "minor": {"label": "Minor storm (scenario)", "factor": 0.6, "storm_size": 15, "analog_event": None,
              "analog": "a typical small storm (about 15 damage reports area-wide)",
              "description": "Scattered wind gusts; isolated tree contact."},
    "moderate": {"label": "Moderate storm (scenario)", "factor": 1.0, "analog_event": "2025-01-06..2025-01-07",
                 "analog": "the January 2025 storm",
                 "description": "Sustained wind with widespread limb contact."},
    "major": {"label": "Major storm (scenario)", "factor": 1.25, "analog_event": "2024-09-26..2024-10-02",
              "analog": "the late-September 2024 storm (Helene's remnants)",
              "description": "Strong, long-lasting wind; many trees down across the area."},
    "severe": {"label": "Severe storm (scenario)", "factor": 1.5, "analog_event": "2025-02-12..2025-02-18",
               "analog": "the February 2025 storm, the largest in the data",
               "description": "Damaging wind or ice; broken poles and downed lines likely."},
}
DEFAULT_SEVERITY = "moderate"

# Susceptibility points (sum is at most 100 before the severity factor).
# 1) Interrupting overhead exposure: overhead primary length (km) whose damage would
#    trip a device this premise depends on. Linear up to the saturation length.
EXPOSURE_MAX_POINTS = 50
EXPOSURE_SATURATION_KM = 15.0  # above the CIR18 maximum (13.3 km) so no premise is clipped; revisit per circuit
# 2) Historical storm events (distinct, grouped by date) in which at least one ARCOS
#    damage record would have interrupted this premise. Linear up to the cap.
HISTORY_MAX_POINTS = 30
HISTORY_SATURATION_EVENTS = 3
# 3) Service drop type (customer layer `kind_of_se`).
SERVICE_POINTS = {"Overhead": 10, "Underground": 0, "Unknown": 5}

SCORE_CAP = 100

# ---- fitted model (pipeline/build_risk_model.py -> data/processed/risk_model.json) ----
MODEL_FEATURES = ["log_storm_size", "log_exposure_km", "hist_rate", "protect_depth", "overhead_service"]
OVERHEAD_SERVICE_VALUE = {"Overhead": 1.0, "Underground": 0.0, "Unknown": 0.5}
# Bands on the recalibrated chance. 5% is about 1 in 20; 15% is below the 19% of premises the
# largest storm on record reached, so "high" means "comparable to that storm for you".
PROB_BANDS = [(0.15, "high"), (0.05, "moderate"), (0.0, "low")]
PROB_BORDERLINE_RATIO = 1.2  # within 20% (relative) of a band edge -> flagged as borderline
INTERVAL_Z = 1.645  # 90% interval
# Confidence for the fitted model: the 90% interval's spread across bands replaces the
# "no validation" deduction; the data-quality deductions below still apply.
INTERVAL_BAND_DEDUCTION = {1: 0, 2: 30, 3: 60}
CONFIDENCE_LEVELS_FITTED = [(80, "high"), (50, "moderate"), (0, "low")]

# Bands on the final heuristic score (after the severity factor).
BANDS = [  # (lower bound inclusive, band)
    (45, "high"),
    (25, "moderate"),
    (0, "low"),
]
BORDERLINE_MARGIN = 4  # points from a band edge at which the result is flagged as borderline

# Confidence: start at 100 and subtract. "High" is not reachable while there is no
# outage-labelled data to validate the score against.
CONFIDENCE_START = 100
CONFIDENCE_DEDUCTIONS = {
    "no_validation": 25,           # no confirmed-outage labels; score is unvalidated
    "inferred_feeder_head": 10,    # substation location / root inferred from device hierarchy
    "gap_on_path": 5,              # per proximity-bridged gap on the supply path (max 2)
    "assumed_coverage_in_chain": 10,  # a device you depend on has assumed branch coverage
    "unknown_mounting_share": 10,  # >5% of interrupting length has unknown mounting
    "approximate_history": 5,      # some of your historical evidence uses approximate matches
    "circuit_root_consistency": 10,   # < 0.95 agreement with upstream_l hierarchy
    "circuit_chain_consistency": 20,  # < 0.95 chain ancestry consistency
    "premise_flag": 25,            # per data-quality flag on the premise
    "unknown_service_type": 5,
}
CONFIDENCE_LEVELS = [(55, "moderate"), (0, "low")]
UNKNOWN_MOUNTING_SHARE = 0.05
CONSISTENCY_THRESHOLD = 0.95
