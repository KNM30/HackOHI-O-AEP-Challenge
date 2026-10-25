import { useRef, type ReactNode } from "react";

export type TabId = "overview" | "explore" | "ask" | "audit";

export interface TabDef {
  id: TabId;
  label: string;
  panel: ReactNode;
}

interface Props {
  tabs: TabDef[];
  active: TabId;
  onChange: (id: TabId) => void;
}

/**
 * WAI-ARIA tabs: arrow keys / Home / End move between tabs; each panel is labelled by its tab.
 * Every panel stays mounted (inactive ones are `hidden`), so switching tabs never resets component
 * state, re-runs requests or tears down the map.
 */
export function JourneyTabs({ tabs, active, onChange }: Props) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (delta: number | "first" | "last") => {
    const i = tabs.findIndex((t) => t.id === active);
    const j = delta === "first" ? 0 : delta === "last" ? tabs.length - 1 : (i + delta + tabs.length) % tabs.length;
    onChange(tabs[j].id);
    refs.current[tabs[j].id]?.focus();
  };
  return (
    <div className="journey">
      <div
        className="journey-tabs"
        role="tablist"
        aria-label="Sections"
        onKeyDown={(e) => {
          const keys: Record<string, number | "first" | "last"> = { ArrowRight: 1, ArrowLeft: -1, Home: "first", End: "last" };
          if (e.key in keys) {
            e.preventDefault();
            move(keys[e.key]);
          }
        }}
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={active === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={active === t.id ? 0 : -1}
            className={`jtab ${active === t.id ? "active" : ""}`}
            onClick={() => onChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div
          key={t.id}
          className="journey-panel"
          role="tabpanel"
          id={`panel-${t.id}`}
          aria-labelledby={`tab-${t.id}`}
          hidden={active !== t.id}
          tabIndex={0}
        >
          {t.panel}
        </div>
      ))}
    </div>
  );
}
