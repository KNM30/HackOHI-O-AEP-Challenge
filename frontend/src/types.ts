// Mirrors backend/app/schemas.py
export interface LatLon {
  lat: number;
  lon: number;
}

export interface CircuitSummary {
  circuit_id: string;
  label: string;
  premises: number;
}

export interface PremiseListItem {
  id: string;
  service_type: string;
  transformer_id: string | null;
}

export interface ChainElement {
  id: string;
  kind: string;
  label: string;
  position: number;
  customers_behind: string;
  location: LatLon | null;
}

export interface SupplyPath {
  length_km: number;
  overhead_km: number;
  underground_km: number;
  unknown_km: number;
  structures: number;
  approximated_gaps: number;
  coordinates: [number, number][];
}

export type DamageRelation = "own_transformer" | "on_supply_path" | "same_protection_zone";

export interface HistoricalDamage {
  id: string;
  report_date: string | null;
  asset_type: string | null;
  damage_type: string | null;
  access_issue: string | null;
  repaired: string | null;
  relation: DamageRelation;
  approx_location: LatLon;
}

export interface HistoricalDamageSummary {
  note: string;
  circuit_records: number;
  circuit_records_placed: number;
  own_transformer: number;
  on_supply_path: number;
  same_protection_zone: number;
  by_date: Record<string, number>;
  records: HistoricalDamage[];
}

export interface PendingCard {
  status: "not_calculated" | "insufficient_data";
  message: string;
}

export interface PremiseContext {
  premise: {
    id: string;
    circuit_id: string;
    circuit_label: string;
    service_type: "Overhead" | "Underground" | "Unknown";
    meters: "single" | "multi-unit";
    location: LatLon;
  };
  transformer: { id: string; mounting: string | null; structure: string | null; premises_served: number } | null;
  upstream_chain: ChainElement[];
  supply_path: SupplyPath | null;
  historical_damage: HistoricalDamageSummary;
  data_quality: {
    flags: string[];
    circuit_root_consistency: number | null;
    circuit_chain_consistency: number | null;
    notes: string[];
  };
  predictions: Record<"restoration" | "guidance" | "alerts", PendingCard>;
}

export interface SeverityOption {
  id: string;
  label: string;
  description: string;
}

export interface RiskFactor {
  name: string;
  value: string;
  points: number | null;
  max_points: number | null;
  explanation: string;
}

export interface RiskResult {
  kind: "pre_storm_risk";
  status: "calculated" | "insufficient_data";
  severity: string;
  severity_label: string;
  severity_options: SeverityOption[];
  band: "low" | "moderate" | "high" | null;
  score: number | null;
  score_note: string;
  confidence: {
    level: "moderate" | "low";
    points: number;
    reasons: { effect: number; text: string }[];
    ceiling_note: string;
  } | null;
  factors: RiskFactor[];
  assumptions: string[];
  missing_inputs: string[];
  could_change: string[];
  fallback_message: string | null;
}

export interface ScenarioLocation {
  id: string;
  label: string;
  location: LatLon | null;
}

export interface ScenarioOption {
  id: string;
  label: string;
  description: string;
  mode: "single" | "multi";
  available: boolean;
  unavailable_reason: string | null;
  locations: ScenarioLocation[];
  default_location_ids: string[];
}

export type ImpactStatus = "not_interrupted" | "repair_dependent" | "isolation_candidate" | "unresolved";

export interface ScenarioResult {
  scenario_id: string;
  scenario_label: string;
  state: "simulated";
  disclaimer: string;
  active_locations: ScenarioLocation[];
  circuit_premises: number;
  initially_interrupted: number;
  repair_dependent: number;
  isolation_candidates: number;
  unresolved: number;
  not_interrupted: number;
  selected_premise: {
    status: ImpactStatus;
    headline: string;
    reasons: { location_id: string; relation: string; text: string }[];
    devices_involved: string[];
  };
  step_restoration: string;
  critical_facilities: CriticalImpact[];
  transformer_impacts: {
    id: string;
    status: Exclude<ImpactStatus, "not_interrupted">;
    repair_dependent: number;
    isolation_candidate: number;
    unresolved: number;
  }[];
  assumptions: string[];
}

export interface MapPoint {
  id: string;
  kind: string;
  label: string;
  location: LatLon;
  premises_served: number | null;
}

export interface CircuitMap {
  circuit_id: string;
  label: string;
  bounds: [[number, number], [number, number]];
  lines: GeoJSON.FeatureCollection<GeoJSON.LineString, { id: string; usage: string; mounting: string; bridge: boolean }>;
  transformers: MapPoint[];
  devices: MapPoint[];
}

export interface CrewParams {
  crews: number;
  crew_size: number;
  hours_per_day: number;
  access_delay_h: number;
  access_scope: "reported" | "all";
  prioritize_critical: boolean;
  restring_assumption: boolean;
}

export interface JobSlot {
  crew: number;
  start_h: number;
  end_h: number;
}

export interface RepairJob {
  id: string;
  label: string;
  evidence: string;
  records: number;
  tasks: { name: string; quantity_low: number; quantity_high: number }[];
  direct_hours_low: number;
  direct_hours_high: number;
  person_hours_low: number;
  person_hours_high: number;
  work_hours_low: number | null;
  work_hours_high: number | null;
  waits: Record<string, [number, number]>;
  crew_min: number;
  crew_useful_max: number;
  customers_waiting: number;
  supported: boolean;
  schedulable: boolean;
  problems: string[];
  partial: string[];
  assumed: string[];
  notes: string[];
  protection_uncertain: boolean;
  optimistic: JobSlot | null;
  conservative: JobSlot | null;
  developer: {
    tasks: {
      name: string;
      source: string;
      unit_hours_low: number | null;
      unit_hours_high: number | null;
      quantity_low: number;
      quantity_high: number;
      drawing: string | null;
    }[];
    structures: string[];
    adders: { name: string; hours: number; source: string }[];
    ilm: number;
    ilm_source: string;
  };
}

export interface RestorationResult {
  state: "simulated";
  time_reference: string;
  disclaimer: string;
  params: CrewParams;
  selected: {
    status: ImpactStatus;
    headline: string;
    display: string;
    lower_h: number | null;
    upper_h: number | null;
    basis: "not_interrupted" | "repair" | "isolation";
    controlling_jobs: string[];
    why: string[];
    confidence: { level: "moderate" | "low"; points: number; reasons: { effect: number; text: string }[]; ceiling_note: string };
    range_kind: "not_interrupted" | "bounded" | "lower_bound_only" | "conditional" | "crew_infeasible" | "insufficient_data";
    conditional: {
      if_isolated_low_h: number;
      if_isolated_high_h: number;
      if_repair_low_h: number | null;
      if_repair_high_h: number | null;
      repair_scope_complete: boolean;
    } | null;
    scope_complete: boolean;
    network_uncertain: boolean;
    uses_assumption: boolean;
    workbook_only_lower_h: number | null;
  };
  overall: {
    complete: boolean;
    lower_h: number | null;
    upper_h: number | null; // null unless every job is scheduled and fully modeled
    modeled_work_upper_h: number | null;
    note: string | null;
    jobs: number;
    jobs_unsupported: number;
    jobs_infeasible: number;
    jobs_partial: number;
    direct_hours_low: number;
    direct_hours_high: number;
    person_hours_low: number;
    person_hours_high: number;
    customers_interrupted: number;
  };
  critical_facilities: (CriticalImpact & { display: string; lower_h: number | null; upper_h: number | null; at_least: boolean })[];
  critical_priority: {
    effect: "no_facility_waiting" | "changed_order" | "already_first";
    hours_earlier: number | null;
    text: string;
  } | null;
  crew_targets: {
    targets: { target_h: number; label: string; crews_needed_optimistic: number | null; crews_needed_conservative: number | null }[];
    scope_complete: boolean;
    note: string;
  } | null;
  jobs: RepairJob[];
  warnings: string[];
  assumptions: string[];
  developer: {
    labor_basis: string;
    ilm: number;
    ilm_source: string;
    ilm_applies_to: string;
    waits_hours: Record<string, [number, number]>;
    adders_not_applied: Record<string, string>;
    source_workbook: string;
  };
}

export interface CriticalImpact {
  kind: "hospital" | "fire_station" | "ambulance_station";
  status: ImpactStatus;
}

export interface SimulationResult {
  impact: ScenarioResult;
  restoration: RestorationResult;
}

// ---- Milestone 4
export type Accessibility = "mobility" | "hearing" | "vision" | "speech" | "cognitive";
export type Channel = "none" | "sms" | "email" | "push" | "voice";

export interface Preferences {
  medical_power_dependent: boolean;
  accessibility: Accessibility[];
}

export interface AlertPrefs {
  opt_in: boolean;
  channel: Channel;
}

export interface SimEvent {
  type: "outage_confirmed" | "restoration_confirmed";
  scenario_key: string;
}

export interface EstimateSignature {
  range_kind: string;
  lower_h: number | null;
  upper_h: number | null;
  confidence: string;
  if_isolated_high_h?: number | null;
  if_repair_high_h?: number | null;
}

export interface LastNotified extends EstimateSignature {
  scenario_key: string;
}

export interface Recommendation {
  id: string;
  category: "emergency" | "routine";
  urgency: "emergency" | "now" | "before the storm" | "during an outage" | "after power returns";
  action: string;
  why: string;
  note: string | null;
  source_note: string | null;
  sources: { id: string; title: string; url: string; verified_on: string }[];
}

export type MessageType = "pre_storm" | "outage_confirmed" | "estimate_updated" | "restoration_complete";

export interface MessagePreview {
  type: MessageType;
  title: string;
  status: "would_send" | "triggered_not_opted_in" | "triggered_no_channel" | "not_triggered";
  status_reason: string;
  dedupe_key: string;
  simulated: true;
  text: string;
  estimate: EstimateSignature | null;
}

export interface AlertsResult {
  disclaimer: string;
  opted_in: boolean;
  channel: Channel;
  channel_label: string;
  channel_ok: boolean;
  warranted_now: string[];
  escalation: string | null;
  timing: string[];
  rules: { id: string; description: string; active: boolean }[];
  messages: MessagePreview[];
}

export interface BriefingRequest {
  premise_id: string;
  severity: string;
  simulation: { scenario_id: string; scenario_label: string; location_ids: string[]; crew: CrewParams } | null;
  preferences: Preferences;
  alerts: AlertPrefs;
  events: SimEvent[];
  last_notified: LastNotified | null;
}

export interface BriefingResponse {
  snapshot_version: string;
  scenario_key: string | null;
  premise_id: string;
  guidance: Recommendation[];
  guidance_note: string;
  alerts: AlertsResult;
  restoration_kind: string | null;
}

export interface PreviousEstimate {
  snapshot_version: string;
  severity: string;
  crew: CrewParams | null;
  scenario_key: string | null;
  range_kind: string | null;
  lower_h: number | null;
  upper_h: number | null;
  risk_band: string | null;
}

export interface AssistantResponse {
  snapshot_version: string;
  mode: "ai" | "fallback";
  status: "ai" | "not_configured" | "provider_failed" | "validation_failed" | "not_shared";
  status_text: string;
  fallback_reason: string | null;
  diagnostics: Record<string, string>;
  intent: string;
  answer: Record<"facts" | "assumptions" | "estimates" | "actions" | "limitations", string[]>;
  disclaimer: string;
}
