import type { Accessibility, AlertPrefs, Channel, Preferences } from "../types";

interface Props {
  prefs: Preferences;
  alerts: AlertPrefs;
  onPrefs: (p: Preferences) => void;
  onAlerts: (a: AlertPrefs) => void;
  onReset: () => void;
  open: boolean;
  onOpen: (open: boolean) => void;
}

const NEEDS: { id: Accessibility; label: string }[] = [
  { id: "mobility", label: "Mobility (may need help to leave home)" },
  { id: "hearing", label: "Hearing" },
  { id: "vision", label: "Vision" },
  { id: "speech", label: "Speech" },
  { id: "cognitive", label: "Cognitive / plain-language support" },
];

export const CHANNELS: { id: Channel; label: string }[] = [
  { id: "none", label: "No channel" },
  { id: "sms", label: "Text message" },
  { id: "email", label: "Email" },
  { id: "push", label: "App notification" },
  { id: "voice", label: "Automated voice call" },
];

export function PreferencesCard({ prefs, alerts, onPrefs, onAlerts, onReset, open, onOpen }: Props) {
  const toggleNeed = (id: Accessibility) =>
    onPrefs({
      ...prefs,
      accessibility: prefs.accessibility.includes(id) ? prefs.accessibility.filter((x) => x !== id) : [...prefs.accessibility, id],
    });
  return (
    <details className="ctx-item prefs" id="prefs" open={open} onToggle={(e) => onOpen(e.currentTarget.open)}>
      <summary>
        <span className="prefs-title">Needs and alerts</span>{" "}
        <span className="muted small">
          medical need: {prefs.medical_power_dependent ? "yes" : "no"}; alerts:{" "}
          {alerts.opt_in ? CHANNELS.find((c) => c.id === alerts.channel)?.label ?? "on" : "off"}
        </span>
      </summary>
      <p className="muted small">
        Only what you choose here is used. Nothing is inferred from utility records, nothing is saved in your browser,
        and it is cleared when you reload. Telling us about a medical need does not register you with the utility or
        guarantee faster restoration.
      </p>
      <label className="small loc-option">
        <input
          type="checkbox"
          checked={prefs.medical_power_dependent}
          onChange={(e) => onPrefs({ ...prefs, medical_power_dependent: e.target.checked })}
        />
        I rely on electrically powered medical equipment or refrigerated medicine
      </label>
      <fieldset className="locations">
        <legend className="small">Accessibility or communication needs</legend>
        {NEEDS.map((n) => (
          <label key={n.id} className="small loc-option">
            <input type="checkbox" checked={prefs.accessibility.includes(n.id)} onChange={() => toggleNeed(n.id)} />
            {n.label}
          </label>
        ))}
      </fieldset>
      <label className="small loc-option">
        <input type="checkbox" checked={alerts.opt_in} onChange={(e) => onAlerts({ ...alerts, opt_in: e.target.checked })} />
        Opt in to outage alerts (demonstration only - nothing is sent and no contact details are collected)
      </label>
      <label className="field compact">
        <span>Preferred channel (demo)</span>
        <select value={alerts.channel} onChange={(e) => onAlerts({ ...alerts, channel: e.target.value as Channel })}>
          {CHANNELS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <div className="row" style={{ marginTop: "0.6rem" }}>
        <button type="button" className="secondary" onClick={onReset}>
          Clear my preferences
        </button>
      </div>
    </details>
  );
}
