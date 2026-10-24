import { useState } from "react";
import type { LoggedMessage } from "../commsState";
import type { AlertPrefs, BriefingResponse, Channel, MessagePreview } from "../types";
import { CHANNELS } from "./PreferencesCard";

interface Props {
  briefing: BriefingResponse | null;
  log: LoggedMessage[];
  canConfirmOutage: boolean;
  outageConfirmed: boolean;
  restored: boolean;
  onConfirmOutage: () => void;
  onConfirmRestored: () => void;
}

const STATUS_LABEL: Record<MessagePreview["status"], string> = {
  would_send: "Would be sent (simulated)",
  triggered_not_opted_in: "Warranted - not opted in",
  triggered_no_channel: "Warranted - no channel selected",
  not_triggered: "Not triggered",
};

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="secondary tiny"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => setDone(true), () => setDone(false));
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

/** Plain answer to "Do I qualify for outage alerts?", from the backend's per-message statuses. */
function eligibility(warranted: MessagePreview | undefined): string {
  if (!warranted) return "No alert is needed right now. Turn on alerts so you are told if that changes.";
  const what = `Yes - your situation qualifies for a ${warranted.title.replace(/ \(simulated\)$/, "").toLowerCase()}.`;
  if (warranted.status === "triggered_not_opted_in") return `${what} Turn on alerts to receive it.`;
  if (warranted.status === "triggered_no_channel") return `${what} Choose how you want to receive it.`;
  return `${what} Alerts are on, so it would be sent to you.`;
}

/** Inline opt-in, next to the eligibility answer (same state as the Needs and alerts panel). */
function AlertOptIn({ alerts, onAlerts }: { alerts: AlertPrefs; onAlerts: (a: AlertPrefs) => void }) {
  return (
    <div className="row optin">
      <label className="small loc-option">
        <input type="checkbox" checked={alerts.opt_in} onChange={(e) => onAlerts({ ...alerts, opt_in: e.target.checked })} />
        Send me outage alerts
      </label>
      <label className="small optin-channel">
        <span className="muted">by</span>{" "}
        <select
          value={alerts.channel}
          aria-label="Alert channel"
          onChange={(e) => onAlerts({ ...alerts, channel: e.target.value as Channel })}
        >
          {CHANNELS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/**
 * Overview: whether alerts are warranted now, the opt-in, and the latest simulated message logged
 * this session. Delivery and de-duplication live in commsState.
 */
export function LatestAlert({
  briefing,
  log,
  alerts,
  onAlerts,
}: {
  briefing: BriefingResponse | null;
  log: LoggedMessage[];
  alerts: AlertPrefs;
  onAlerts: (a: AlertPrefs) => void;
}) {
  const a = briefing?.alerts;
  if (!a) return <p className="muted small">Choose your home first.</p>;
  const last = log[log.length - 1];
  const warranted = a.messages.find((m) => m.status !== "not_triggered");
  return (
    <div className="alert-preview">
      <p className="answer-line">{eligibility(warranted)}</p>
      <AlertOptIn alerts={alerts} onAlerts={onAlerts} />
      <p className="muted small">Demonstration only: nothing is sent and no contact details are collected.</p>
      {a.escalation && <p className="small note">{a.escalation}</p>}
      {last && (
        <>
          <p className="small">
            <strong>Latest message:</strong> {last.title} <span className="muted">- simulated, via {a.channel_label.toLowerCase()}</span>
          </p>
          <pre className="msg">{last.text}</pre>
        </>
      )}
    </div>
  );
}

export function AlertsCard({ briefing, log, canConfirmOutage, outageConfirmed, restored, onConfirmOutage, onConfirmRestored }: Props) {
  const a = briefing?.alerts;
  const [preview, setPreview] = useState<MessagePreview["type"]>("pre_storm");
  const shown = a?.messages.find((m) => m.type === preview);
  return (
    <div aria-live="polite">
      {!a && <p className="muted small">Choose your home first.</p>}
      {a && (
        <>
          <p className="sim-banner">{a.disclaimer}</p>
          <dl className="counts">
            <dt>Alert warranted now</dt>
            <dd>{a.warranted_now.length ? a.warranted_now.map((t) => t.replace(/_/g, " ")).join(", ") : "none"}</dd>
            <dt>You opted in</dt>
            <dd>{a.opted_in ? "yes" : "no"}</dd>
            <dt>Channel</dt>
            <dd>{a.channel_label}</dd>
          </dl>
          {a.escalation && <p className="small note">{a.escalation}</p>}

          <h4>Simulated outage events</h4>
          <div className="row">
            <button type="button" onClick={onConfirmOutage} disabled={!canConfirmOutage || outageConfirmed}>
              Simulate: outage confirmed
            </button>
            <button type="button" className="secondary" onClick={onConfirmRestored} disabled={!outageConfirmed || restored}>
              Simulate: power restored
            </button>
          </div>
          <p className="muted small">
            {canConfirmOutage
              ? "Nothing here is a real outage. Change crews or access delay after confirming to see whether an update is warranted."
              : "Run a damage scenario that cuts power to your home to enable these."}
          </p>

          <h4>Message previews</h4>
          <div className="tabs" role="group" aria-label="Message type">
            {a.messages.map((m) => (
              <button
                key={m.type}
                type="button"
                aria-pressed={preview === m.type}
                className={`tab ${preview === m.type ? "active" : ""} st-${m.status}`}
                onClick={() => setPreview(m.type)}
              >
                {m.type.replace(/_/g, " ")}
              </button>
            ))}
          </div>
          {shown && (
            <div className="preview">
              <p className="small">
                <strong>{STATUS_LABEL[shown.status]}</strong> - {shown.status_reason}
              </p>
              <pre className="msg">{shown.text}</pre>
              <Copy text={shown.text} />
            </div>
          )}

          <h4>Simulated message log ({log.length})</h4>
          {log.length === 0 ? (
            <p className="muted small">No messages yet. A message is logged once when it is warranted, you are opted in, and a channel is selected.</p>
          ) : (
            <ol className="log small">
              {log.map((m) => (
                <li key={m.dedupe_key}>
                  <strong>{m.title}</strong> via {a.channel_label.toLowerCase()} <Copy text={m.text} />
                  <details>
                    <summary>Show message</summary>
                    <pre className="msg">{m.text}</pre>
                  </details>
                </li>
              ))}
            </ol>
          )}
          <details>
            <summary>Prototype alert rules</summary>
            <ul className="small">
              {a.rules.map((r) => (
                <li key={r.id}>
                  {r.active ? "Active: " : ""}
                  {r.description}
                </li>
              ))}
              {a.timing.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </details>
        </>
      )}
    </div>
  );
}
