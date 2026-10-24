"""Field classification for customer-facing outputs.

`CUSTOMER_SAFE` lists the only source fields (per layer) whose values may reach the
browser, usually after renaming/bucketing. Anything not listed is internal.
`SENSITIVE` fields are additionally never written to processed files.
"""

CUSTOMER_SAFE: dict[str, dict[str, str]] = {
    "customer": {
        "kind_of_se": "service type (Overhead / Underground)",
        "circuit_id": "shown only as a circuit label, e.g. 'Circuit 18'",
        "customer_c": "meter count at the service point (shown as 'single' / 'multi-unit')",
        "geometry": "only the selected premise's own point; map overview uses transformers",
    },
    "transformer": {
        "mounting": "overhead / underground equipment",
        "structure_": "pole / pad",
        "geometry": "transformer location (equipment, not a home)",
    },
    "fuse": {"device_typ": "device type", "mounting": "mounting", "geometry": "location"},
    "recloser": {"device_typ": "device type", "geometry": "location"},
    "switch": {"device_typ": "device type", "mounting": "mounting", "geometry": "location"},
    "primary": {"usage": "Backbone / Primary / Lateral", "mounting": "overhead / underground",
                "geometry": "line geometry"},
    "pole": {},
    "secondary": {},
    "damage": {
        "Report_Tim": "date only, labelled historical",
        "Asset_Type": "asset category",
        "Inform_Wor": "damage category",
        "Repaired": "historical repair status",
        "Access_Iss": "access issue flag",
        "geometry": "rounded to ~100 m for display; exact point used only server-side",
    },
    "ambulance": {}, "fire": {}, "hospital": {},
}

SENSITIVE: dict[str, list[str]] = {
    "customer": ["critical_c", "special_op", "address", "address_nu", "road_name", "road_id",
                 "street_cod", "anno_strin", "city", "macss_mete", "premise_nu", "aep_locati",
                 "aep_xfmr_l", "service_po", "service__1"],
    "damage": ["Outage_Num", "Incident_W", "TASK_Crew", "TASK_Job_I", "Reporting_", "Reporting1",
               "Repaired_B", "Crew_Area", "District"],
    "fuse": ["scada_cont", "global_id"], "recloser": ["scada_cont", "global_id"],
    "switch": ["scada_cont", "global_id"], "transformer": ["scada_cont", "global_id"],
    "ambulance": ["NAME", "ADDRESS"], "fire": ["NAME", "ADDRESS"], "hospital": ["NAME", "ADDRESS"],
}


def classify(layer: str, column: str) -> str:
    if column in SENSITIVE.get(layer, []):
        return "sensitive"
    if column in CUSTOMER_SAFE.get(layer, {}):
        return "customer-safe"
    return "internal"
