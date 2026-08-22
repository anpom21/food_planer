import { useState } from "react";
import { saveSettings, type PlanningSettings, type Profile } from "./api";

// Issue #19 — the per-Profile Settings screen. The settled behavioural
// reference is the prototype's recommended variant (prototype/settings-screen,
// "variant D"): a boxed layout of one card holding days-to-plan,
// suggestions-per-day and the known-vs-unknown lean together; one card holding
// the priority order as a drag-to-reorder list; and a full-width Inspiration
// textarea. Preferred shops are a separate ticket and deliberately absent here.
//
// Settings are per-Profile (ADR 0001) and saved on their own via
// PUT /api/profiles/{id}/settings — the screen never round-trips name and email
// just to save a slider.

// The four priorities in a stable display order, keyed by the value stored in
// settings.priority. Order in the list expresses what matters most, so no
// numeric weights are guessed at.
const PRIORITY_LABELS: Record<string, string> = {
  cheap: "Cheap",
  quick: "Quick & easy",
  delicious: "Delicious",
  healthy: "Healthy",
};

// A narrow number box with − and + buttons inside one bordered pill, rather
// than the native browser spinner, which is miserable on a tablet.
function Stepper({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  const clamp = (n: number) => Math.max(min, Math.min(max, n));
  return (
    <div className="field">
      <label>{label}</label>
      <div className="stepper">
        <button
          type="button"
          className="step-btn"
          aria-label={`Decrease ${label}`}
          onClick={() => onChange(clamp(value - 1))}
        >
          −
        </button>
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(clamp(Number(e.target.value) || 0))}
        />
        <button
          type="button"
          className="step-btn"
          aria-label={`Increase ${label}`}
          onClick={() => onChange(clamp(value + 1))}
        >
          +
        </button>
      </div>
    </div>
  );
}

export function SettingsScreen({
  profile,
  onSaved,
}: {
  profile: Profile;
  onSaved: (profile: Profile) => void;
}) {
  // The draft is the working copy; nothing persists until Save. Starting from
  // the profile's stored settings means the form reflects what's on disk.
  const [draft, setDraft] = useState<PlanningSettings>(profile.settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const patch = (fields: Partial<PlanningSettings>) => {
    setDraft((prev) => ({ ...prev, ...fields }));
    setSaved(false);
  };

  // Reorder by dragging: when a dragged row is moved over another, the two
  // swap so the list settles into the person's chosen sequence. The saved
  // order is exactly the four items as they end up here.
  const movePriority = (from: number, to: number) => {
    if (from === to) return;
    setDraft((prev) => {
      const priority = [...prev.priority];
      const [moved] = priority.splice(from, 1);
      priority.splice(to, 0, moved);
      return { ...prev, priority };
    });
    setSaved(false);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await saveSettings(profile.id, draft);
      onSaved(updated);
      setSaved(true);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="settings" onSubmit={submit}>
      <h1>Planning settings</h1>
      <p className="muted">
        Your preferences, yours alone — used every time you plan a week.
      </p>

      <section className="settings-card">
        <div className="row">
          <Stepper
            label="Days to plan"
            value={draft.daysToPlan}
            min={1}
            max={14}
            onChange={(daysToPlan) => patch({ daysToPlan })}
          />
          <Stepper
            label="Suggestions / day"
            value={draft.suggestionsPerDay}
            min={1}
            max={10}
            onChange={(suggestionsPerDay) => patch({ suggestionsPerDay })}
          />
        </div>
        <div className="field">
          <label htmlFor="known-vs-unknown">Known vs. unknown dishes</label>
          <input
            id="known-vs-unknown"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={draft.knownVsUnknownBias}
            onChange={(e) =>
              patch({ knownVsUnknownBias: Number(e.target.value) })
            }
          />
          <div className="slider-labels">
            <span>Mostly known</span>
            <span>Mostly unknown</span>
          </div>
        </div>
      </section>

      <section className="settings-card">
        <label>
          Priority order{" "}
          <span className="hint">(drag to reorder, top = matters most)</span>
        </label>
        <ul className="drag-list">
          {draft.priority.map((key, index) => (
            <li
              key={key}
              draggable
              className={dragIndex === index ? "dragging" : undefined}
              onDragStart={() => setDragIndex(index)}
              onDragEnd={() => setDragIndex(null)}
              onDragOver={(e) => {
                e.preventDefault();
                if (dragIndex !== null && dragIndex !== index) {
                  movePriority(dragIndex, index);
                  setDragIndex(index);
                }
              }}
            >
              <span className="rank-num">{index + 1}</span>
              <span className="grip" aria-hidden="true">
                ⠿
              </span>
              {PRIORITY_LABELS[key] ?? key}
            </li>
          ))}
        </ul>
      </section>

      <section className="settings-card">
        <label htmlFor="inspiration">
          Inspiration{" "}
          <span className="hint">— steer invented dishes in your own words</span>
        </label>
        <textarea
          id="inspiration"
          placeholder="e.g. more Vietnamese food, less pasta"
          value={draft.inspiration}
          onChange={(e) => patch({ inspiration: e.target.value })}
        />
      </section>

      <div className="settings-actions">
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save settings"}
        </button>
        {saved && <span className="saved-note">Saved ✓</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </form>
  );
}
