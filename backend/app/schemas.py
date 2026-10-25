"""Response models. These are the allowlist: only fields declared here reach the browser."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LatLon(BaseModel):
    lat: float
    lon: float


class CircuitSummary(BaseModel):
    circuit_id: str
    label: str
    premises: int


class PremiseListItem(BaseModel):
    id: str
    service_type: str
    transformer_id: str | None


class PremiseInfo(BaseModel):
    id: str
    circuit_id: str
    circuit_label: str
    service_type: Literal["Overhead", "Underground", "Unknown"]
    meters: Literal["single", "multi-unit"]
    location: LatLon


class TransformerInfo(BaseModel):
    id: str
    mounting: str | None
    structure: str | None
    premises_served: int


class ChainElement(BaseModel):
    id: str
    kind: str
    label: str
    position: int  # 0 = nearest the premise
    customers_behind: str  # bucketed count, e.g. "about 130"
    location: LatLon | None


class SupplyPath(BaseModel):
    length_km: float
    overhead_km: float
    underground_km: float
    unknown_km: float
    structures: int
    approximated_gaps: int  # flagged digitising-gap bridges along the path
    coordinates: list[list[float]]  # [lat, lon] from premise transformer to feeder head


class HistoricalDamage(BaseModel):
    id: str
    report_date: str | None
    asset_type: str | None
    damage_type: str | None
    access_issue: str | None
    repaired: str | None
    relation: Literal["own_transformer", "on_supply_path", "same_protection_zone"]
    approx_location: LatLon  # rounded ~100 m


class HistoricalDamageSummary(BaseModel):
    note: str
    circuit_records: int
    circuit_records_placed: int
    own_transformer: int
    on_supply_path: int
    same_protection_zone: int
    by_date: dict[str, int]
    records: list[HistoricalDamage]


class DataQuality(BaseModel):
    flags: list[str]
    circuit_root_consistency: float | None
    circuit_chain_consistency: float | None
    notes: list[str]


class PendingCard(BaseModel):
    status: Literal["not_calculated", "insufficient_data"]
    message: str


class Predictions(BaseModel):
    # Risk is served by /api/premises/{id}/risk (depends on the severity scenario input).
    restoration: PendingCard
    guidance: PendingCard
    alerts: PendingCard


class PremiseContext(BaseModel):
    premise: PremiseInfo
    transformer: TransformerInfo | None
    upstream_chain: list[ChainElement]
    supply_path: SupplyPath | None
    historical_damage: HistoricalDamageSummary
    data_quality: DataQuality
    predictions: Predictions


class SeverityOption(BaseModel):
    id: str
    label: str
    description: str


class RiskFactor(BaseModel):
    name: str
    value: str
    # heuristic: points toward the 0-100 score. fitted model: change in your chance, in percentage
    # points, against an average premise in the service area (signed; max_points is None)
    points: float | None
    max_points: float | None
    explanation: str
    direction: Literal["raises", "lowers", "neutral"] | None = None


class ConfidenceReason(BaseModel):
    effect: int  # points subtracted (negative)
    text: str


class Confidence(BaseModel):
    level: Literal["high", "moderate", "low"]
    points: int
    reasons: list[ConfidenceReason]
    ceiling_note: str


class CalibrationRow(BaseModel):
    bin: str
    mean_predicted: float
    observed: float
    rows: int


class RiskModelCard(BaseModel):
    """How the fitted model was trained and how well it did on storms it had not seen."""
    label_definition: str
    training_premises: int
    training_circuits: int
    training_storms: int
    pooled_auc: float
    within_storm_auc: float
    heuristic_within_storm_auc: float
    calibration: list[CalibrationRow]
    notes: list[str]


class RiskResult(BaseModel):
    kind: Literal["pre_storm_risk"] = "pre_storm_risk"
    status: Literal["calculated", "insufficient_data"]
    method: Literal["fitted_model", "heuristic"] = "heuristic"
    severity: str
    severity_label: str
    severity_options: list[SeverityOption]
    band: Literal["low", "moderate", "high"] | None
    # fitted model: recalibrated chance that storm damage cuts your supply, with a 90% interval
    probability: float | None = None
    probability_low: float | None = None
    probability_high: float | None = None
    score: int | None  # heuristic points 0-100, NOT a probability (heuristic method only)
    score_note: str = "Heuristic points (0-100) used only to place the band. Not a probability."
    model_card: RiskModelCard | None = None
    confidence: Confidence | None
    factors: list[RiskFactor]
    assumptions: list[str]
    missing_inputs: list[str]
    could_change: list[str]
    fallback_message: str | None


class ScenarioLocation(BaseModel):
    id: str
    label: str
    location: LatLon | None


class ScenarioOption(BaseModel):
    id: str
    label: str
    description: str
    mode: Literal["single", "multi"]
    available: bool
    unavailable_reason: str | None
    locations: list[ScenarioLocation]
    default_location_ids: list[str]


class ScenarioCatalog(BaseModel):
    premise_id: str
    scenarios: list[ScenarioOption]


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(max_length=40)
    location_ids: list[str] | None = Field(default=None, max_length=300)


class ImpactReason(BaseModel):
    location_id: str
    relation: str
    text: str


class PremiseImpact(BaseModel):
    status: Literal["not_interrupted", "repair_dependent", "isolation_candidate", "unresolved"]
    headline: str
    reasons: list[ImpactReason]
    devices_involved: list[str]


class TransformerImpact(BaseModel):
    id: str
    status: Literal["repair_dependent", "isolation_candidate", "unresolved"]
    repair_dependent: int
    isolation_candidate: int
    unresolved: int


class ScenarioResult(BaseModel):
    scenario_id: str
    scenario_label: str
    state: Literal["simulated"]
    disclaimer: str
    active_locations: list[ScenarioLocation]
    circuit_premises: int
    initially_interrupted: int
    repair_dependent: int
    isolation_candidates: int
    unresolved: int
    not_interrupted: int
    selected_premise: PremiseImpact
    step_restoration: str
    transformer_impacts: list[TransformerImpact]
    critical_facilities: list["CriticalImpact"] = []
    assumptions: list[str]


class CrewParamsIn(BaseModel):
    crews: int = Field(2, ge=1, le=20)
    crew_size: int = Field(4, ge=2, le=8)
    hours_per_day: float = Field(16, ge=8, le=16)
    access_delay_h: float = Field(0, ge=0, le=48)
    access_scope: Literal["reported", "all"] = "reported"
    prioritize_critical: bool = True
    restring_assumption: bool = True  # team assumption for conductor replacement (labor_config.RESTRING)


class CrewParamsOut(BaseModel):  # echo of the inputs used (limits are enforced on the request)
    crews: int
    crew_size: int
    hours_per_day: float
    access_delay_h: float
    access_scope: str
    prioritize_critical: bool = True
    restring_assumption: bool = True


class SimulationRequest(BaseModel):
    premise_id: str = Field(max_length=20)
    scenario_id: str = Field(max_length=40)
    scenario_label: str = Field(max_length=120)
    location_ids: list[str] = Field(min_length=1, max_length=300)
    crew: CrewParamsIn = CrewParamsIn()


class RepairTask(BaseModel):
    name: str
    quantity_low: float
    quantity_high: float


class JobSlot(BaseModel):
    crew: int
    start_h: float
    end_h: float


class DevTask(BaseModel):
    name: str
    source: str
    unit_hours_low: float | None
    unit_hours_high: float | None
    quantity_low: float
    quantity_high: float
    drawing: str | None = None  # structure_drawings.pdf page / D.S. assembly


class DevAdder(BaseModel):
    name: str
    hours: float
    source: str


class JobDeveloper(BaseModel):
    tasks: list[DevTask]
    structures: list[str] = []  # sample structures the repair template stands for
    adders: list[DevAdder]
    ilm: float
    ilm_source: str


class RepairJob(BaseModel):
    id: str
    label: str
    evidence: str
    records: int
    tasks: list[RepairTask]
    direct_hours_low: float
    direct_hours_high: float
    person_hours_low: float
    person_hours_high: float
    work_hours_low: float | None
    work_hours_high: float | None
    waits: dict[str, list[float]]
    crew_min: int
    crew_useful_max: int
    customers_waiting: int
    supported: bool
    schedulable: bool
    problems: list[str]
    partial: list[str]
    assumed: list[str] = []  # team assumptions filling a workbook gap (labelled, never workbook data)
    notes: list[str]
    protection_uncertain: bool
    optimistic: JobSlot | None
    conservative: JobSlot | None
    developer: JobDeveloper


class ConditionalOutcomes(BaseModel):
    """Isolation case: two alternative outcomes, never merged into one interval."""
    if_isolated_low_h: float
    if_isolated_high_h: float
    if_repair_low_h: float | None
    if_repair_high_h: float | None
    repair_scope_complete: bool


RangeKind = Literal["not_interrupted", "bounded", "lower_bound_only", "conditional", "crew_infeasible",
                    "insufficient_data"]


class CustomerRestoration(BaseModel):
    status: Literal["not_interrupted", "repair_dependent", "isolation_candidate", "unresolved"]
    headline: str
    display: str
    # earliest / latest modeled times; read together with range_kind (they are NOT an interval
    # for "conditional", and only lower bounds for "lower_bound_only")
    lower_h: float | None
    upper_h: float | None
    basis: Literal["not_interrupted", "repair", "isolation"]
    controlling_jobs: list[str]
    why: list[str]
    confidence: Confidence
    range_kind: RangeKind
    conditional: ConditionalOutcomes | None
    scope_complete: bool
    network_uncertain: bool
    # the estimate relies on the team's conductor re-stringing assumption; workbook_only_lower_h is the
    # earliest repair-based time from workbook data alone (a lower bound), for side-by-side display
    uses_assumption: bool = False
    workbook_only_lower_h: float | None = None


class OverallRestoration(BaseModel):
    complete: bool  # every job scheduled AND fully modeled; otherwise only a lower bound is defensible
    lower_h: float | None
    upper_h: float | None  # None unless complete
    modeled_work_upper_h: float | None  # developer view: end of the modeled (possibly partial) work
    note: str | None
    jobs: int
    jobs_unsupported: int
    jobs_infeasible: int
    jobs_partial: int
    direct_hours_low: float
    direct_hours_high: float
    person_hours_low: float
    person_hours_high: float
    customers_interrupted: int


class DeveloperView(BaseModel):
    labor_basis: str
    ilm: float
    ilm_source: str
    ilm_applies_to: str
    waits_hours: dict[str, list[float]]
    adders_not_applied: dict[str, str]
    source_workbook: str


class CriticalImpact(BaseModel):
    """A critical facility (type only - never name or location) and its simulated impact."""
    kind: Literal["hospital", "fire_station", "ambulance_station"]
    status: Literal["not_interrupted", "repair_dependent", "isolation_candidate", "unresolved"]


class CriticalRestoration(CriticalImpact):
    display: str
    lower_h: float | None
    upper_h: float | None  # None when only a lower bound is defensible
    at_least: bool


class CriticalPriority(BaseModel):
    """What the critical-facility priority rule changed, against the same scenario with the rule flipped."""
    effect: Literal["no_facility_waiting", "changed_order", "already_first"]
    hours_earlier: float | None  # optimistic hours by which priority restores a facility sooner
    text: str


class CrewTarget(BaseModel):
    target_h: float
    label: str
    crews_needed_optimistic: int | None  # None: not reachable with up to 20 crews
    crews_needed_conservative: int | None


class CrewTargets(BaseModel):
    targets: list[CrewTarget]
    scope_complete: bool
    note: str


class PaceDay(BaseModel):
    day: int  # days after the storm's first report (day 0 = first report date)
    share_repaired: float


class Backtest(BaseModel):
    """Replay only: the crews this model needs to match the repair pace recorded in ARCOS."""
    event: str
    records: int
    records_used: int
    excluded_closure_lag: int
    observed_finish_day: int  # day by which BACKTEST_SHARE of the used records were repaired
    observed_pace: list[PaceDay]
    implied_crews_optimistic: int | None  # None: not reached within BACKTEST_MAX_CREWS
    implied_crews_conservative: int | None
    your_crews_finish_days: list[float]  # [optimistic, conservative] with the crews you selected
    note: str


class RestorationResult(BaseModel):
    state: Literal["simulated"]
    time_reference: str
    disclaimer: str
    params: CrewParamsOut
    selected: CustomerRestoration
    overall: OverallRestoration
    critical_facilities: list[CriticalRestoration] = []
    critical_priority: CriticalPriority | None = None
    crew_targets: CrewTargets | None = None
    backtest: Backtest | None = None
    jobs: list[RepairJob]
    warnings: list[str]
    assumptions: list[str]
    developer: DeveloperView


class SimulationResult(BaseModel):
    impact: ScenarioResult
    restoration: RestorationResult


class MapPoint(BaseModel):
    id: str
    kind: str
    label: str
    location: LatLon
    premises_served: int | None = None


class CircuitMap(BaseModel):
    circuit_id: str
    label: str
    bounds: list[list[float]]  # [[south, west], [north, east]]
    lines: dict  # GeoJSON FeatureCollection with allowlisted properties (built by pipeline)
    transformers: list[MapPoint]
    devices: list[MapPoint]


# ---------------------------------------------------------------- Milestone 4
Accessibility = Literal["mobility", "hearing", "vision", "speech", "cognitive"]
Channel = Literal["none", "sms", "email", "push", "voice"]


class Preferences(BaseModel):
    """Needs the customer explicitly declared this session. Never inferred from source data."""
    medical_power_dependent: bool = False
    accessibility: list[Accessibility] = Field(default_factory=list, max_length=5)


class AlertPrefs(BaseModel):
    opt_in: bool = False
    channel: Channel = "none"


class SimEvent(BaseModel):
    type: Literal["outage_confirmed", "restoration_confirmed"]
    scenario_key: str = Field(max_length=40)


class EstimateSignature(BaseModel):
    range_kind: str
    lower_h: float | None
    upper_h: float | None
    confidence: str
    if_isolated_high_h: float | None = None
    if_repair_high_h: float | None = None


class LastNotified(EstimateSignature):
    scenario_key: str = Field(max_length=40)


class GuidanceSource(BaseModel):
    id: str
    title: str
    url: str
    verified_on: str


class Recommendation(BaseModel):
    id: str
    category: Literal["emergency", "routine"]
    urgency: Literal["emergency", "now", "before the storm", "during an outage", "after power returns"]
    action: str
    why: str
    note: str | None
    source_note: str | None
    sources: list[GuidanceSource]


class MessagePreview(BaseModel):
    type: Literal["pre_storm", "outage_confirmed", "estimate_updated", "restoration_complete"]
    title: str
    status: Literal["would_send", "triggered_not_opted_in", "triggered_no_channel", "not_triggered"]
    status_reason: str
    dedupe_key: str
    simulated: Literal[True] = True
    text: str
    estimate: EstimateSignature | None = None


class AlertRule(BaseModel):
    id: str
    description: str
    active: bool


class AlertsResult(BaseModel):
    disclaimer: str
    opted_in: bool
    channel: Channel
    channel_label: str
    channel_ok: bool
    warranted_now: list[str]
    escalation: str | None
    timing: list[str]
    rules: list[AlertRule]
    messages: list[MessagePreview]


class SimulationSpec(BaseModel):
    scenario_id: str = Field(max_length=40)
    scenario_label: str = Field(max_length=120)
    location_ids: list[str] = Field(min_length=1, max_length=300)
    crew: CrewParamsIn = CrewParamsIn()


class BriefingRequest(BaseModel):
    premise_id: str = Field(max_length=20)
    severity: str = Field("moderate", max_length=20)
    simulation: SimulationSpec | None = None
    preferences: Preferences = Preferences()
    alerts: AlertPrefs = AlertPrefs()
    events: list[SimEvent] = Field(default_factory=list, max_length=10)
    last_notified: LastNotified | None = None


class BriefingResponse(BaseModel):
    snapshot_version: str
    scenario_key: str | None
    premise_id: str
    guidance: list[Recommendation]
    guidance_note: str
    alerts: AlertsResult
    restoration_kind: RangeKind | None


class PreviousEstimate(BaseModel):
    """What the customer saw before (for 'why did my estimate change?'). Numbers/enums only."""
    snapshot_version: str = Field(max_length=40)
    severity: str = Field(max_length=20)
    crew: CrewParamsIn | None = None
    scenario_key: str | None = Field(None, max_length=40)
    range_kind: str | None = Field(None, max_length=30)
    lower_h: float | None = None
    upper_h: float | None = None
    risk_band: str | None = Field(None, max_length=20)


class AssistantRequest(BaseModel):
    briefing: BriefingRequest
    question: str = Field(min_length=1, max_length=500)
    previous: PreviousEstimate | None = None


class AnswerSections(BaseModel):
    facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    estimates: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AssistantResponse(BaseModel):
    snapshot_version: str
    mode: Literal["ai", "fallback"]
    # ai | standard answer because: not configured / provider failed (incl. refusal) / failed validation / not shared
    status: Literal["ai", "not_configured", "provider_failed", "validation_failed", "not_shared"]
    status_text: str  # short customer-facing explanation of the status
    fallback_reason: str | None  # developer detail (no secrets)
    diagnostics: dict[str, str] = Field(default_factory=dict)  # developer view: model, latency, tokens, checks
    intent: str
    answer: AnswerSections
    disclaimer: str

class AuditEntry(BaseModel):
    """One returned decision: hashed IDs, inputs and an output summary only (no typed text)."""
    seq: int
    at: str  # UTC, ISO 8601
    session: str
    endpoint: str
    premise_id: str | None
    inputs: dict[str, str | int | float | bool | None]
    outputs: dict[str, str | int | float | bool | None]
    model: str


ScenarioResult.model_rebuild()
