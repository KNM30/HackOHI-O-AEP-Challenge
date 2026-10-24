import { useEffect, useMemo, useRef, useState } from "react";
import type { PremiseListItem } from "../types";

interface Props {
  premises: PremiseListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  demoId: string;
  openSignal: number; // bumped by the parent to open the picker (e.g. after switching circuit)
}

const MAX_SHOWN = 60;

/** Compact searchable picker: a disclosure button that opens a search field and a short list. */
export function PremiseSelector({ premises, selectedId, onSelect, demoId, openSignal }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    return q ? premises.filter((p) => p.id.includes(q)) : premises;
  }, [premises, query]);

  useEffect(() => {
    if (openSignal > 0) {
      setQuery("");
      setOpen(true);
    }
  }, [openSignal]);

  useEffect(() => {
    if (!open) return;
    search.current?.focus();
    const outside = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  const choose = (id: string) => {
    onSelect(id);
    setOpen(false);
    toggle.current?.focus();
  };

  return (
    <div className="picker" ref={root}>
      <div className="row">
        <button
          ref={toggle}
          type="button"
          className="secondary picker-toggle"
          aria-expanded={open}
          aria-controls="premise-picker"
          onClick={() => setOpen((o) => !o)}
        >
          <span className="muted small">Your home{selectedId ? " - demo ID" : ""}</span>{" "}
          <span className="mono">{selectedId ?? "Choose..."}</span>{" "}
          <span aria-hidden>▾</span>
        </button>
        <button type="button" onClick={() => onSelect(demoId)}>
          Load demo
        </button>
      </div>
      {open && (
        <div
          className="picker-pop"
          id="premise-picker"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              toggle.current?.focus();
            }
          }}
        >
          <label className="field compact">
            <span>Search by anonymized demo ID</span>
            <input ref={search} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. PRM-00770FFC" />
          </label>
          <ul className="premise-list" aria-label="Homes">
            {matches.slice(0, MAX_SHOWN).map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  aria-current={p.id === selectedId ? "true" : undefined}
                  className={p.id === selectedId ? "selected" : ""}
                  onClick={() => choose(p.id)}
                >
                  <span className="mono">{p.id}</span>
                  <span className="muted small">{p.service_type.toLowerCase()} service</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="row picker-foot">
            <span className="muted small">
              {matches.length > MAX_SHOWN ? `Showing ${MAX_SHOWN} of ${matches.length} - refine the search.` : `${matches.length} match(es)`}
            </span>
            <button
              type="button"
              className="secondary tiny"
              onClick={() => choose(premises[Math.floor(Math.random() * premises.length)].id)}
              disabled={premises.length === 0}
            >
              Random home
            </button>
          </div>
          <p className="muted small">
            Demo IDs stand in for addresses. You can also click a transformer on the map in Explore scenarios.
          </p>
        </div>
      )}
    </div>
  );
}
