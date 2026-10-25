"""Prototype alert rules (documented in docs/alerts_and_guidance.md). Not AEP policy."""

# Pre-storm alert when the pre-storm risk band (under the chosen severity scenario) is at
# least this level. With the fitted model, "high" means a 15% or greater chance.
PRE_STORM_MIN_BAND = "high"
BAND_RANK = {"low": 0, "moderate": 1, "high": 2}

# An "estimate updated" message is warranted when, after a simulated outage confirmation,
# the latest-modeled restoration time moves by at least max(MIN_H, FRACTION x previous),
# the kind of estimate changes (e.g. becomes "cannot estimate"), or confidence drops.
ESTIMATE_CHANGE_MIN_H = 2.0
ESTIMATE_CHANGE_MIN_FRACTION = 0.25

# Declared reliance on powered medical equipment + an outage that may exceed this many
# hours (or cannot be estimated) adds an escalation note. It never implies priority.
MEDICAL_ESCALATION_H = 4.0

CHANNELS = {
    "none": "No channel selected",
    "sms": "Text message",
    "email": "Email",
    "push": "App notification",
    "voice": "Automated voice call",
}

TIMING = [
    "Pre-storm: once, when the storm-severity scenario puts your risk in the high band (a 15% or greater chance; a "
    "real system would use forecast timing, which this prototype does not have).",
    "Outage confirmed: only after an explicit (simulated) confirmation that your home is out.",
    "Estimate updated: when the restoration estimate changes meaningfully, gets less certain, or can no longer be "
    "estimated - not on every recalculation.",
    "Restoration complete: only after an explicit (simulated) confirmation; never because a predicted time passed.",
]

LABEL_PREFIX = "[SIMULATED - prototype message, not from AEP]"
LABEL_SUFFIX = "- HackOHI/O Outage Concierge prototype (simulated scenario)"
