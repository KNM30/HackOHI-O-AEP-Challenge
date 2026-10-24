"""Rule-based selection of curated guidance (no generated safety instructions).

Inputs are the backend's own results plus needs the customer explicitly declared in
this session. Nothing is inferred from source data (the customer-layer life-support
flag is never used).
"""
from __future__ import annotations

from . import schemas as s
from .guidance_content import ITEMS, SOURCES, VERIFIED_ON

URGENCY_ORDER = ["emergency", "now", "before the storm", "during an outage", "after power returns"]
LONG_OUTAGE_H = 24.0   # medication / extreme-temperature guidance
FOOD_FRIDGE_H = 4.0    # Ready.gov: refrigerator keeps food cold ~4 h


def _hours_text(h: float) -> str:
    return f"{h:.0f} hours" if h < 48 else f"{h / 24:.1f} days"


def select(risk: s.RiskResult | None, restoration: s.CustomerRestoration | None,
           prefs: s.Preferences, channel: str = "none") -> list[s.Recommendation]:
    picks: dict[str, str] = {}  # item id -> why

    band = risk.band if risk and risk.status == "calculated" else None
    elevated = band in ("moderate", "high")
    interrupted = restoration is not None and restoration.status != "not_interrupted"
    kind = restoration.range_kind if restoration else None
    # Planning horizon: a time the outage could plausibly reach. For an incomplete estimate
    # only its lower bound is defensible ("at least"); a modeled upper time is not a bound.
    horizon, at_least = None, False
    if restoration and kind == "bounded":
        horizon = restoration.upper_h
    elif restoration and kind == "lower_bound_only":
        horizon, at_least = restoration.lower_h, True
    elif restoration and kind == "conditional" and restoration.conditional:
        c = restoration.conditional  # plan for the repair-based outcome
        if c.repair_scope_complete:
            horizon = c.if_repair_high_h
        else:  # partly modeled repair: only "at least" is defensible
            horizon, at_least = c.if_repair_low_h, True
    unknown_duration = interrupted and (horizon is None or at_least)

    def length(h: float) -> str:
        return ("at least " if at_least else "about ") + _hours_text(h)

    if risk is None or risk.status != "calculated":
        picks["kit"] = "We could not estimate your outage risk, so we suggest general storm preparation."
    if elevated:
        picks["kit"] = f"Your pre-storm risk is {band} under the selected storm scenario."
        picks["co_detector"] = "Generators and fuel-burning heaters are common during outages."
        picks["downed_lines"] = "Storms that cause outages often bring lines down."
    if band == "high" or interrupted:
        picks["generator_co"] = "You may use a generator or fuel-burning equipment if the power goes out."
        picks["downed_lines"] = "Storm damage near you is likely in this scenario."
    if interrupted:
        picks["life_threat"] = "Your home loses power in this simulation."
        picks["food_closed"] = "Your home loses power in this simulation."
        picks["unplug"] = "Power may return with surges."
        if horizon is not None and horizon > FOOD_FRIDGE_H:
            picks["food_discard"] = (f"The simulated outage could last {length(horizon)}, longer than a "
                                     "refrigerator keeps food cold.")
        if (horizon is not None and horizon > LONG_OUTAGE_H) or unknown_duration:
            picks["extreme_temps"] = ("The simulated outage could last more than a day." if not unknown_duration
                                      else "We cannot rule out an outage of more than a day.")
        if kind in ("insufficient_data", "crew_infeasible") or unknown_duration:
            picks["plan_long"] = {
                "insufficient_data": "A repair your supply depends on cannot be estimated.",
                "crew_infeasible": "The selected crews cannot do a required repair under these assumptions.",
            }.get(kind, "Part of the repair work is not covered by the labor data, so the real outage may be longer "
                        "than modeled.")
        if restoration and restoration.network_uncertain:
            picks.setdefault("plan_long", "Which equipment controls your outage is uncertain in the model, so the "
                                          "estimate could change.")
    elif restoration is not None:
        picks["stay_ready"] = "This simulated damage does not interrupt your home."

    # Declared needs only
    if prefs.medical_power_dependent:
        picks["medical_plan"] = "You told us you rely on electrically powered medical equipment or refrigerated " \
                                "medicine."
        if interrupted and ((horizon is not None and horizon > LONG_OUTAGE_H) or unknown_duration):
            picks["medication_long"] = "Your simulated outage could exceed a day and you declared a medical need."
    if prefs.accessibility:
        picks["support_contact"] = "You told us about accessibility needs (" + ", ".join(prefs.accessibility) + ")."
        if {"hearing", "speech"} & set(prefs.accessibility) and channel == "voice":
            picks["alert_channel"] = "Voice alerts may not suit the communication needs you declared."

    out = []
    for item_id, why in picks.items():
        it = ITEMS[item_id]
        out.append(s.Recommendation(
            id=item_id, category=it["category"], urgency=it["urgency"], action=it["action"], why=why,
            note=it.get("note"), source_note=it.get("source_note"),
            sources=[s.GuidanceSource(id=sid, title=SOURCES[sid]["title"], url=SOURCES[sid]["url"],
                                      verified_on=VERIFIED_ON) for sid in it["sources"]]))
    out.sort(key=lambda r: (r.category != "emergency", URGENCY_ORDER.index(r.urgency), r.id))
    return out
