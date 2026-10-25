import { divIcon, type FitBoundsOptions, type LatLngBoundsExpression, type Map as LeafletMap } from "leaflet";
import { useEffect } from "react";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Marker,
  Pane,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import type { CircuitMap, DamageRelation, PremiseContext, PremiseListItem, ScenarioResult } from "../types";

interface Props {
  layers: CircuitMap;
  context: PremiseContext | null;
  premises: PremiseListItem[];
  onSelect: (id: string) => void;
  scenario: ScenarioResult | null;
  showHistorical: boolean;
}

const IMPACT_COLOR = {
  repair_dependent: "#c92a2a",
  unresolved: "#e8590c",
  isolation_candidate: "#2b8a3e",
} as const;

const RELATION_LABEL: Record<DamageRelation, string> = {
  own_transformer: "your service transformer",
  on_supply_path: "on your supply path",
  same_protection_zone: "same protection zone",
};

const SIM_ICON = divIcon({ className: "sim-icon", html: "<span></span>", iconSize: [18, 18], iconAnchor: [9, 9] });

// The map lives in a tab panel that may be hidden (display: none). Leaflet cannot measure a hidden
// container, so a fit requested while hidden is kept and applied once the map has a size again.
const pendingFit = new WeakMap<LeafletMap, [LatLngBoundsExpression, FitBoundsOptions]>();

function fit(map: LeafletMap, bounds: LatLngBoundsExpression, options: FitBoundsOptions) {
  const el = map.getContainer();
  if (el.clientWidth === 0 || el.clientHeight === 0) {
    pendingFit.set(map, [bounds, options]);
    return;
  }
  pendingFit.delete(map);
  map.invalidateSize();
  map.fitBounds(bounds, options);
}

function TrackSize() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const ro = new ResizeObserver(() => {
      if (el.clientWidth === 0 || el.clientHeight === 0) return;
      map.invalidateSize();
      const p = pendingFit.get(map);
      if (p) fit(map, ...p);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

// When a simulation result arrives, show the premise together with the simulated damage.
function FocusScenario({ context, scenario }: { context: PremiseContext | null; scenario: ScenarioResult | null }) {
  const map = useMap();
  useEffect(() => {
    if (!scenario || !context) return;
    const pts = scenario.active_locations.flatMap((l) => (l.location ? [[l.location.lat, l.location.lon] as [number, number]] : []));
    if (!pts.length) return;
    fit(map, [[context.premise.location.lat, context.premise.location.lon], ...pts], { padding: [40, 40], maxZoom: 16 });
  }, [map, scenario, context]);
  return null;
}

function FitTo({ bounds }: { bounds: [[number, number], [number, number]] }) {
  const map = useMap();
  useEffect(() => {
    fit(map, bounds, { padding: [16, 16] });
  }, [map, bounds]);
  return null;
}

function FocusPremise({ context }: { context: PremiseContext | null }) {
  const map = useMap();
  useEffect(() => {
    if (context?.supply_path?.coordinates.length) {
      fit(map, [[context.premise.location.lat, context.premise.location.lon], ...context.supply_path.coordinates], {
        padding: [32, 32],
        maxZoom: 16,
      });
    }
  }, [map, context]);
  return null;
}

export function NetworkMap({ layers, context, premises, onSelect, scenario, showHistorical }: Props) {
  const chainIds = new Set(context?.upstream_chain.map((c) => c.id));
  const impact = new Map(scenario?.transformer_impacts.map((t) => [t.id, t]));
  return (
    <MapContainer className="map" center={[37.18, -80.01]} zoom={13} scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <TrackSize />
      <FitTo bounds={layers.bounds} />
      <FocusPremise context={context} />
      <FocusScenario context={context} scenario={scenario} />
      <GeoJSON
        key={layers.circuit_id}
        data={layers.lines}
        style={(f) => ({
          color: f?.properties.mounting === "Underground" ? "#8a6d3b" : "#2f6fb0",
          weight: f?.properties.usage === "Backbone" ? 3 : 1.5,
          dashArray: f?.properties.mounting === "Underground" ? "4 4" : undefined,
          opacity: 0.7,
        })}
      />
      {layers.transformers.map((t) => {
        const imp = impact.get(t.id);
        return (
        <CircleMarker
          key={`${t.id}-${imp?.status ?? "none"}`}
          center={[t.location.lat, t.location.lon]}
          radius={imp ? 5 : 3}
          pathOptions={
            imp
              ? { color: IMPACT_COLOR[imp.status], fillColor: IMPACT_COLOR[imp.status], weight: 1, fillOpacity: 0.85 }
              : { color: "#555", weight: 1, fillOpacity: 0.6 }
          }
        >
          <Popup>
            <strong>Service transformer</strong>
            {imp && (
              <>
                <br />
                <em>
                  Simulation: {imp.repair_dependent} wait for repair, {imp.isolation_candidate} possible earlier
                  restoration, {imp.unresolved} unresolved
                </em>
              </>
            )}
            <br />
            Serves {t.premises_served} home(s) or business(es):
            <ul className="popup-list">
              {premises
                .filter((p) => p.transformer_id === t.id)
                .slice(0, 12)
                .map((p) => (
                  <li key={p.id}>
                    <button type="button" className="link" onClick={() => onSelect(p.id)}>
                      {p.id}
                    </button>
                  </li>
                ))}
            </ul>
          </Popup>
        </CircleMarker>
        );
      })}
      {layers.devices.map((d) => (
        <CircleMarker
          key={d.id}
          center={[d.location.lat, d.location.lon]}
          radius={chainIds.has(d.id) ? 7 : 4}
          pathOptions={{
            color: d.kind === "recloser" ? "#7b3fa0" : d.kind === "switch" ? "#2a7f62" : "#c77700",
            weight: chainIds.has(d.id) ? 3 : 1,
            fillOpacity: 0.85,
          }}
        >
          <Tooltip>{d.label}</Tooltip>
        </CircleMarker>
      ))}
      {context && (
        <Pane name="selection" style={{ zIndex: 650 }}>
          {context.supply_path && (
            <Polyline positions={context.supply_path.coordinates} pathOptions={{ color: "#d6336c", weight: 5, opacity: 0.85 }}>
              <Tooltip sticky>Your supply path to the feeder head</Tooltip>
            </Polyline>
          )}
          {showHistorical &&
            context.historical_damage.records.map((r) => (
            <CircleMarker
              key={r.id}
              center={[r.approx_location.lat, r.approx_location.lon]}
              radius={6}
              pathOptions={{ color: "#b02a37", fillColor: "#f8d7da", fillOpacity: 0.7, weight: 1.5, dashArray: "2 2" }}
            >
              <Tooltip>
                Historical ({r.report_date}): {r.damage_type ?? "damage"} - {RELATION_LABEL[r.relation]}. Location approximate.
              </Tooltip>
            </CircleMarker>
          ))}
          {scenario?.active_locations.map(
            (l) =>
              l.location && (
                <Marker key={`sim-${l.id}`} position={[l.location.lat, l.location.lon]} icon={SIM_ICON}>
                  <Tooltip>SIMULATED damage: {l.label}</Tooltip>
                </Marker>
              ),
          )}
          <CircleMarker
            center={[context.premise.location.lat, context.premise.location.lon]}
            radius={9}
            pathOptions={{ color: "#111", fillColor: "#ffd43b", fillOpacity: 1, weight: 2 }}
          >
            <Tooltip permanent direction="top">
              Your home (approximate)
            </Tooltip>
          </CircleMarker>
        </Pane>
      )}
    </MapContainer>
  );
}
