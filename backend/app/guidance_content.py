"""Curated preparation and safety guidance (single source of approved wording).

Every cited statement was checked against the source page on VERIFIED_ON. Items
without a verified source say so (source ids empty) and are written as general
practice, not attributed to an organisation. The AI assistant may explain these
items but may not add safety instructions of its own.
"""

VERIFIED_ON = "2026-10-24"

SOURCES = {
    "readygov_outages": dict(title="Ready.gov - Power Outages", url="https://www.ready.gov/power-outages",
                             publisher="U.S. Department of Homeland Security", page_updated="2026-06-04"),
    "cdc_co": dict(title="CDC - Prevent Carbon Monoxide Poisoning (Natural Disasters)",
                   url="https://www.cdc.gov/natural-disasters/psa-toolkit/prevent-carbon-monoxide-poisoning.html",
                   publisher="Centers for Disease Control and Prevention", page_updated="reviewed 2026-08-25"),
    "apco_safety": dict(title="Appalachian Power - Safety", url="https://www.appalachianpower.com/safety/",
                        publisher="Appalachian Power (AEP)", page_updated=None),
    "apco_lines": dict(title="Appalachian Power - Power Line Safety",
                       url="https://www.appalachianpower.com/safety/power-lines",
                       publisher="Appalachian Power (AEP)", page_updated=None),
}

# category: "emergency" (life-safety) or "routine" (preparation)
# urgency: "emergency" > "now" > "before the storm" > "during an outage" > "after power returns"
ITEMS = {
    "downed_lines": dict(
        category="emergency", urgency="emergency",
        action="Stay away from downed lines and anything touching them, and treat every line as live. Keep "
               "children and pets away. Report downed lines and damaged poles to Appalachian Power at 800-956-4237.",
        sources=["apco_lines", "apco_safety"]),
    "life_threat": dict(
        category="emergency", urgency="emergency",
        action="If anyone's life or health is in immediate danger, call 911.",
        sources=[], source_note="General emergency practice; not quoted from the sources above."),
    "generator_co": dict(
        category="emergency", urgency="emergency",
        action="If you use a generator, run it only outdoors, at least 20 feet from doors, windows and vents, and "
               "let Appalachian Power know you are running one. Never use a gas stove or oven to heat your home.",
        sources=["cdc_co", "readygov_outages", "apco_safety"]),
    "kit": dict(
        category="routine", urgency="before the storm",
        action="Gather flashlights for everyone, batteries, a battery-powered radio, water, non-perishable food "
               "and important medicines.",
        sources=["readygov_outages", "apco_safety"]),
    "co_detector": dict(
        category="routine", urgency="before the storm",
        action="Make sure you have a battery-operated (or battery back-up) carbon monoxide detector.",
        sources=["readygov_outages", "cdc_co"]),
    "medical_plan": dict(
        category="routine", urgency="now",
        action="Talk to your medical provider about a power-outage plan for powered medical devices and "
               "refrigerated medicine, including another way to power or refrigerate them.",
        sources=["readygov_outages"],
        note="Telling this app about a medical need does not register you with the utility and does not "
             "guarantee faster restoration."),
    "medication_long": dict(
        category="routine", urgency="after power returns",
        action="If power is out for more than a day, refrigerated medication may need to be replaced unless its "
               "label says otherwise. Ask your doctor or pharmacist.",
        sources=["readygov_outages"]),
    "food_closed": dict(
        category="routine", urgency="during an outage",
        action="Keep the refrigerator and freezer closed. A refrigerator keeps food cold for about 4 hours and a "
               "full freezer for about 48 hours.",
        sources=["readygov_outages"]),
    "food_discard": dict(
        category="routine", urgency="after power returns",
        action="Throw out food that has been at 40°F or warmer for 2 hours or more, or that smells or looks "
               "unusual. When in doubt, throw it out.",
        sources=["readygov_outages"]),
    "unplug": dict(
        category="routine", urgency="during an outage",
        action="Unplug appliances and electronics to protect them from surges when power returns, and leave one "
               "light switch on so you know when it is back.",
        sources=["readygov_outages", "apco_safety"]),
    "extreme_temps": dict(
        category="routine", urgency="during an outage",
        action="If it gets very hot or cold, go to a community location with power; check with local officials "
               "for heating or cooling locations.",
        sources=["readygov_outages"]),
    "support_contact": dict(
        category="routine", urgency="before the storm",
        action="Arrange for someone to check on you and help if you need to leave or get supplies.",
        sources=[], source_note="General preparation practice based on your declared needs; not quoted from the "
                                "sources above."),
    "alert_channel": dict(
        category="routine", urgency="before the storm",
        action="Choose an alert channel you can reliably receive (for example text instead of voice).",
        sources=[], source_note="Prototype suggestion based on your declared communication needs."),
    "plan_long": dict(
        category="routine", urgency="now",
        action="Plan for a possibly long outage: the simulated estimate is incomplete or unavailable, so prepare as "
               "if it could last more than a day.",
        sources=["readygov_outages"]),
    "stay_ready": dict(
        category="routine", urgency="before the storm",
        action="Your home is not interrupted in this simulation, but storms can damage other equipment. Keep "
               "your basic kit ready.",
        sources=["readygov_outages"]),
}
