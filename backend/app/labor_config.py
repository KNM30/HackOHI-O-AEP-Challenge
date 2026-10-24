"""Repair templates, labor-unit assumption, waiting delays and scheduler limits.

Single source for restoration assumptions; documented in docs/restoration_model.md.
Labor values themselves come from data/processed/labor_reference.json (built from
Install_Labor_HackOHIO.xlsx by pipeline/build_labor.py) and are never typed here.

Quantities are (optimistic, conservative) pairs. "per_phase" quantities are
multiplied by the span's phase count (unknown phases -> 1 optimistic, 3 conservative).
"""

# ---- labor unit interpretation (DEMO ASSUMPTION) ---------------------------------
# The workbook does not say whether INSTALL/REMOVE hours are per person or per crew.
# The challenge guidance (ILM x direct labor = total person-hours) suggests
# person-hours, so that is the default. "crew_hours" is supported for comparison:
# total person-hours become hours x ILM x crew size, and durations no longer shrink
# as people are added.
LABOR_HOURS_BASIS = "person_hours"  # or "crew_hours"

ILM_APPLIES_TO = "eligible direct labor (CU install/removal hours + 'additional labor' adders), once per job"

# ---- repair templates -------------------------------------------------------------
# task: (name, workbook source, actions, quantity mode, (opt, cons) quantity)
#   source: ("category", <table name>) or ("connectors", "average")
#   actions: which workbook columns apply - removal hours are used only when a part is
#            physically removed (never assumed equal to install).
TEMPLATES = {
    "overhead_conductor": dict(
        label="Repair damaged overhead line",
        crew_min=2, crew_useful_max=4,
        tasks=[
            ("Splice / reconnect conductor", ("connectors", "average"), ("install",), "per_phase", (2, 2)),
            ("Replace damaged insulator", ("category", "Insulator"), ("install", "remove"), "per_phase", (0, 1)),
        ],
        partial=("The workbook has no labor unit for re-stringing or replacing conductor along a span; only splicing "
                 "and re-attachment are counted, so a long conductor replacement would take longer."),
        restring=True,  # RESTRING (team assumption) fills the partial scope when switched on
        material_wait=False,
    ),
    "pole": dict(
        label="Replace broken pole",
        crew_min=3, crew_useful_max=5,
        tasks=[
            ("Pole (by height class)", ("pole", None), ("install", "remove"), "fixed", (1, 1)),
            ("Crossarm (three-phase framing)", ("category", "Crossarm"), ("install", "remove"), "three_phase_only",
             (1, 1)),
            ("Pin", ("category", "Pin"), ("install", "remove"), "per_phase", (1, 1)),
            ("Insulator", ("category", "Insulator"), ("install", "remove"), "per_phase", (1, 1)),
            ("Re-attach conductor", ("connectors", "average"), ("install",), "per_phase", (0, 1)),
            ("Guy (if angle / dead-end pole)", ("category", "Guying"), ("install", "remove"), "fixed", (0, 1)),
            ("Anchor (if guyed)", ("category", "Anchor"), ("install",), "fixed", (0, 1)),
            ("Grounding", ("category", "Grounding"), ("install", "remove"), "fixed", (0, 1)),
        ],
        partial=None,
        material_wait=True,
    ),
    "fuse_cutout": dict(
        label="Replace damaged fuse cutout",
        crew_min=2, crew_useful_max=2,
        tasks=[("Fuse cutout", ("category", "Fuse Cutout"), ("install", "remove"), "per_phase", (1, 1))],
        partial=None, material_wait=False,
    ),
    "recloser": dict(
        label="Replace damaged recloser",
        crew_min=2, crew_useful_max=3,
        tasks=[("Recloser", ("category", "Recloser"), ("install", "remove"), "per_phase", (1, 1)),
               ("Equipment lead", ("category", "Equipment Lead"), ("install", "remove"), "per_phase", (1, 2))],
        partial=None, material_wait=True,
    ),
    "switch": dict(
        label="Replace damaged switch",
        crew_min=2, crew_useful_max=3,
        tasks=[("Switch", ("category", "Switch"), ("install", "remove"), "fixed", (1, 1))],
        partial=None, material_wait=True,
    ),
    "transformer": dict(
        label="Replace damaged service transformer",
        crew_min=2, crew_useful_max=3,
        tasks=[("Transformer (by kVA)", ("transformer", None), ("install", "remove"), "fixed", (1, 1)),
               ("Equipment lead", ("category", "Equipment Lead"), ("install", "remove"), "fixed", (1, 2)),
               ("Transformer fuse cutout", ("category", "Fuse Cutout"), ("install", "remove"), "fixed", (0, 1))],
        partial=None, material_wait=True,
    ),
    "secondary": dict(
        label="Repair damaged secondary line",
        crew_min=2, crew_useful_max=2,
        tasks=[("Secondary conductor attachment", ("category", "Secondary Conductor Attachment"),
                ("install", "remove"), "fixed", (1, 2)),
               ("Splice / reconnect secondary", ("connectors", "average"), ("install",), "fixed", (2, 4))],
        partial="The workbook has no labor unit for re-stringing secondary conductor; only attachments and splices "
                "are counted.",
        material_wait=False,
    ),
}

# ---- conductor re-stringing (TEAM ASSUMPTION, not AEP data) -------------------------
# The workbook has no labor unit for replacing primary conductor along a span. With the
# scenario input "restring_assumption" on (default), an overhead line repair adds:
#   - dead-ending the replacement conductor at both structures: workbook Dead-End row,
#     0 (re-tied on tangent structures, already covered by splices) .. 2 per phase;
#   - pulling, sagging and tying in the replacement conductor: the one assumed rate below,
#     direct hours per phase per 100 ft of the damaged span (GIS span length), so the
#     4.5 ILM still applies once. For scale, a small pole installs in about 1.9 workbook
#     hours; a median 205 ft single-phase span gives 0.6 .. 1.6 direct hours.
# With it off, the repair keeps the workbook-only scope and a lower-bound estimate.
RESTRING = dict(
    hours_per_100ft_per_phase=(0.3, 0.8),
    max_span_ft=500,  # longer edges are mapping artifacts (proximity bridges); capped, never extrapolated
    pull_task="Pull and sag replacement conductor (team assumption)",
    dead_end_task="Dead-end replacement conductor at both structures",
    note=("Includes our team's assumed time for replacing the damaged wire (0.3 - 0.8 direct hours per phase per "
          "100 ft of span). The AEP labor workbook has no entry for this work."),
)

# ---- structure drawings (structure_drawings.pdf, 9 image-only pages, read visually) ------
# Which sample structure each template stands for, and the AEP distribution-standard
# (D.S.) assembly behind each task. The drawings fix *which* components a repair
# touches and how phase count changes the framing (single-phase pole-top pin, p. 5;
# three-phase crossarm, p. 9); quantities and hours still come from the templates and
# the workbook. Page numbers are 1-based PDF pages.
STRUCTURE_DRAWINGS = {
    "overhead_conductor": "tangent spans: single-phase p. 5, three-phase p. 9",
    "pole": ("tangent p. 5 (1-ph) / p. 9 (3-ph); dead-end p. 3 (1-ph) / p. 8 (3-ph); taps pp. 4, 6, 7 - "
             "guy and anchor apply only to the dead-end and tap structures"),
    "fuse_cutout": "transformer poles pp. 1-2 (cutout + bracket + fuse link)",
    "recloser": None,  # not shown in the sample drawings
    "switch": None,    # not shown in the sample drawings
    "transformer": "transformer poles pp. 1-2",
    "secondary": "transformer poles pp. 1-2 (twisted cable secondary and risers)",
}
TASK_DRAWINGS = {
    "Splice / reconnect conductor": "D.S. 70-x / D.S. 74 connector (pp. 1-4, 6-8)",
    "Replace damaged insulator": "D.S. 30-x pin & insulator assembly (pp. 5, 9)",
    "Pole (by height class)": "pole shown on every structure; size class from GIS height/class",
    "Crossarm (three-phase framing)": "D.S. 20-x crossarm (p. 8), D.S. 26-x fiberglass crossarm (p. 9)",
    "Pin": "D.S. 30-B pole-top / crossarm pin (pp. 5, 9)",
    "Insulator": "D.S. 30-A pin insulator (pp. 5, 7, 9); dead-end D.S. 31-x (pp. 3, 4, 6-8)",
    "Re-attach conductor": "D.S. 40-x wire tie (pp. 5, 9) / D.S. 70-x connector",
    "Guy (if angle / dead-end pole)": "D.S. 400 guying assembly (pp. 3, 4, 6-8)",
    "Anchor (if guyed)": "anchor end of D.S. 400 guying assembly (pp. 3, 4, 6-8)",
    "Grounding": "D.S. 65 grounding assembly (pp. 1, 2, 4, 6)",
    "Fuse cutout": "D.S. 61-x cutout, D.S. 32-E bracket, D.S. 1001-x fuse link (pp. 1-2)",
    "Transformer fuse cutout": "D.S. 61-x cutout, D.S. 32-E bracket, D.S. 1001-x fuse link (pp. 1-2)",
    "Transformer (by kVA)": "D.S. 1000-x transformer (pp. 1-2)",
    "Equipment lead": "D.S. 75-A #4 copper lead / hot-line tap (pp. 1-2)",
    "Secondary conductor attachment": "D.S. 502 twisted cable secondary, D.S. 1002 risers (pp. 1-2)",
    "Splice / reconnect secondary": "D.S. 70-x connector (pp. 1-2)",
    "Dead-end replacement conductor at both structures": "D.S. 31-x primary dead-end assembly (pp. 3, 4, 6-8)",
    "Pull and sag replacement conductor (team assumption)": "conductor span between structures (pp. 5, 9); "
                                                            "no D.S. assembly - assumed rate",
}

# Damage that cannot be estimated from the workbook -> explicit incomplete estimate.
UNSUPPORTED = {
    "underground_primary": "Underground cable repair (fault location, excavation, splicing or termination) has no "
                           "labor entry in the workbook, and excavation hours need a volume that is not available.",
    "unknown_mounting": "The damaged span's overhead/underground status is unknown (a mapping gap), so the repair "
                        "type cannot be chosen.",
    "unknown_asset": "The damaged asset type has no repair mapping.",
}

# Pole height class boundaries used by the workbook's pole table (feet).
POLE_CLASS = [(35, "Small"), (55, "Medium"), (10_000, "Large")]

# ---- labor adders (direct labor, so the ILM applies) --------------------------------
# One access adder per job at most, only when the damage record reports an access issue.
# "Access Constraint Adder" duplicates "Restricted Access Work" and is not also applied.
ACCESS_ADDER = "Difficult Location"  # workbook "Labor only work" original intent (Restricted Access Work, 0.5 h)
BACKYARD_ADDER = "Backyard Adder"    # used instead when special equipment is a backyard bucket
NOT_APPLIED_ADDERS = {
    "Hand Dig": "per cubic foot - no excavation volume is available",
    "Rock Hole": "per cubic foot - no excavation volume is available",
    "Junction Pole Work": "no hours in the workbook",
    "Access Constraint Adder": "duplicates Restricted Access Work",
}

# ---- waiting delays (elapsed time; never multiplied by the ILM) ---------------------
# (optimistic, conservative) hours
ASSESSMENT_H = (1.0, 3.0)          # damage patrol / assessment before crews can start or switch
WEATHER_HOLD_H = (0.0, 2.0)        # wind/ice must subside before bucket work
MATERIAL_WAIT_H = (0.0, 4.0)       # pole / transformer / recloser / switch material staging
SWITCHING_H_PER_SWITCH = (0.5, 1.5)  # travel to and operate one manual switch (one responder, sequential)
REENERGIZE_H = (0.25, 0.5)         # safety checks and re-energisation after isolation or repair

# ---- crew / workday limits -------------------------------------------------------------
CREWS_RANGE = (1, 20)
CREW_SIZE_RANGE = (2, 8)
HOURS_PER_DAY_RANGE = (8, 16)
ACCESS_DELAY_RANGE_H = (0, 48)
DEFAULTS = dict(crews=2, crew_size=4, hours_per_day=16, access_delay_h=0.0, access_scope="reported")
