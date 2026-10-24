import type { PremiseContext } from "../types";

const RELATION_TEXT = {
  own_transformer: "at your service transformer",
  on_supply_path: "on your supply path",
  same_protection_zone: "elsewhere in a protection zone you depend on",
} as const;

export function FactsPanel({ ctx }: { ctx: PremiseContext }) {
  const { premise, transformer, upstream_chain, supply_path, historical_damage: hd, data_quality } = ctx;
  return (
    <div className="facts-panel">
      <p className="muted small">From the supplied (anonymized, historical) data.</p>
      <dl className="facts">
        <dt>Demo ID</dt>
        <dd className="mono">{premise.id}</dd>
        <dt>Circuit</dt>
        <dd>{premise.circuit_label}</dd>
        <dt>Service</dt>
        <dd>
          {premise.service_type} service, {premise.meters === "single" ? "single meter" : "multi-unit"}
        </dd>
        {transformer && (
          <>
            <dt>Transformer</dt>
            <dd>
              {transformer.mounting?.toLowerCase()} {transformer.structure?.toLowerCase()}-mounted, shared by{" "}
              {transformer.premises_served} premise(s)
            </dd>
          </>
        )}
        {supply_path && (
          <>
            <dt>Supply path</dt>
            <dd>
              {supply_path.length_km} km to the feeder head ({supply_path.overhead_km} km overhead,{" "}
              {supply_path.underground_km} km underground), {supply_path.structures} structures
            </dd>
          </>
        )}
      </dl>

      <details>
        <summary>Protective devices between you and the substation ({upstream_chain.length})</summary>

      <ol className="chain">
        {upstream_chain.map((c) => (
          <li key={c.id}>
            <span className={`dot dot-${c.kind}`} aria-hidden />
            <span>
              {c.label}
              <span className="muted small"> - serves {c.customers_behind} customers</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="muted small">
        Listed nearest-first. A fault is normally cleared by the nearest device upstream of it, so damage behind a
        device closer to you affects fewer customers.
      </p>

      </details>
      <details>
        <summary>
          Past damage that would have affected you: {hd.on_supply_path + hd.same_protection_zone + hd.own_transformer}{" "}
          records
        </summary>

      <p className="muted small">{hd.note}</p>
      <ul className="stats">
        <li>
          <strong>{hd.own_transformer}</strong> {RELATION_TEXT.own_transformer}
        </li>
        <li>
          <strong>{hd.on_supply_path}</strong> {RELATION_TEXT.on_supply_path}
        </li>
        <li>
          <strong>{hd.same_protection_zone}</strong> {RELATION_TEXT.same_protection_zone}
        </li>
      </ul>
      {Object.keys(hd.by_date).length > 0 && (
        <p className="small">
          By month:{" "}
          {Object.entries(hd.by_date)
            .map(([m, n]) => `${m} (${n})`)
            .join(", ")}
        </p>
      )}
      <p className="muted small">
        {hd.circuit_records_placed} of {hd.circuit_records} damage records on this circuit could be placed on the
        network.
      </p>

      </details>
      <details>
        <summary>Data quality and limitations</summary>
        <ul className="small">
          <li>
            Network orientation agrees with the supplied device hierarchy:{" "}
            {data_quality.circuit_root_consistency === null ? "n/a" : `${Math.round(data_quality.circuit_root_consistency * 100)}%`}
          </li>
          <li>
            Upstream device chains consistent with the mapped network:{" "}
            {data_quality.circuit_chain_consistency === null ? "n/a" : `${Math.round(data_quality.circuit_chain_consistency * 100)}%`}
          </li>
          {data_quality.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
