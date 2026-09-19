import { useEffect, useState } from "react";
import { Stepper } from "./SettingsScreen";
import {
  listDishes,
  planWeek,
  type Dish,
  type PlanningRun,
  type Profile,
  type SettingsOverride,
  type Suggestion,
} from "./api";

// Issue #23 — Plan a Week: one button, one pass, a board of day columns.
//
// The plan owns the screen. Controls collapse into a top bar so they never
// crowd out the plan: the "⚡ Plan my week" button and a chip summarising the
// settings this run would use. One press fires a single structured LLM call
// that returns the whole week at once, so no dish repeats across days.
//
// Issue #25 — Per-run settings override: the chip is a button that opens a
// modal to bend days, suggestions-per-day and the known-vs-unknown lean for
// *this run only*. The override is applied to one prompt and never written back
// to the Profile, so planning a short week never means editing (and forgetting
// to restore) your saved defaults.

// The three fields the profile carries that a per-run override can bend. The
// chip and the modal both read the override when present, else the defaults.
function defaultsOf(profile: Profile): SettingsOverride {
  const s = profile.settings;
  return {
    daysToPlan: s.daysToPlan,
    suggestionsPerDay: s.suggestionsPerDay,
    knownVsUnknownBias: s.knownVsUnknownBias,
  };
}

function sameAsDefaults(a: SettingsOverride, b: SettingsOverride): boolean {
  return (
    a.daysToPlan === b.daysToPlan &&
    a.suggestionsPerDay === b.suggestionsPerDay &&
    a.knownVsUnknownBias === b.knownVsUnknownBias
  );
}

function biasWord(bias: number): string {
  if (bias <= 0.34) return "mostly known";
  if (bias >= 0.66) return "mostly new";
  return "a mix";
}

function settingsSummary(s: SettingsOverride): string {
  return `${s.daysToPlan} days · ${s.suggestionsPerDay}/day · ${biasWord(
    s.knownVsUnknownBias,
  )}`;
}

// The just-for-this-run modal behind the settings chip. It is unmistakably
// labelled as a per-run override and carries a "Reset to my defaults" link, so
// nobody is ever left wondering whether they have changed their saved settings.
function OverrideModal({
  draft,
  defaults,
  onChange,
  onReset,
  onClose,
}: {
  draft: SettingsOverride;
  defaults: SettingsOverride;
  onChange: (draft: SettingsOverride) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  const isOverridden = !sameAsDefaults(draft, defaults);
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal override-modal">
        <h2>Plan this week with…</h2>
        <p className="override-note">
          🕐 Just for this run — your saved defaults stay untouched.
        </p>
        <div className="row">
          <Stepper
            label="Days to plan"
            value={draft.daysToPlan}
            min={1}
            max={14}
            onChange={(daysToPlan) => onChange({ ...draft, daysToPlan })}
          />
          <Stepper
            label="Suggestions / day"
            value={draft.suggestionsPerDay}
            min={1}
            max={10}
            onChange={(suggestionsPerDay) =>
              onChange({ ...draft, suggestionsPerDay })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="override-bias">Known vs. unknown dishes</label>
          <input
            id="override-bias"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={draft.knownVsUnknownBias}
            onChange={(e) =>
              onChange({ ...draft, knownVsUnknownBias: Number(e.target.value) })
            }
          />
          <div className="slider-labels">
            <span>Mostly known</span>
            <span>Mostly unknown</span>
          </div>
        </div>
        <div className="modal-actions override-actions">
          <button
            type="button"
            className="link-btn"
            onClick={onReset}
            disabled={!isOverridden}
          >
            Reset to my defaults
          </button>
          <button className="btn primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// A known dish names the library entry it came from; an invented one is "New
// to you". Ingredients never appear on the card — only behind Details.
function SuggestionCard({
  suggestion,
  dishesById,
  onDetails,
}: {
  suggestion: Suggestion;
  dishesById: Map<string, Dish>;
  onDetails: () => void;
}) {
  const known = suggestion.sourceDish
    ? dishesById.get(suggestion.sourceDish)
    : null;
  return (
    <article className="sugg-card">
      <h3 className="sugg-title">{suggestion.title}</h3>
      <p className="sugg-desc">{suggestion.description}</p>
      <div className="sugg-chips">
        {suggestion.sourceDish ? (
          <span className="chip known">
            ⭐ {known ? known.title : "Known dish"}
          </span>
        ) : (
          <span className="chip unknown">✨ New to you</span>
        )}
        <span className="chip">⏱ {suggestion.prepTimeMinutes} min</span>
        <span className="chip">~{suggestion.estimatedCost} kr</span>
        {suggestion.discounts.length > 0 && (
          <span className="chip discount">
            🏷️ {suggestion.discounts.length} on offer
          </span>
        )}
      </div>
      <button className="btn ghost sugg-details" onClick={onDetails}>
        Details
      </button>
    </article>
  );
}

// Details opens the full suggestion — the description in full and the ingredient
// list that the card deliberately withholds.
function DetailsModal({
  suggestion,
  known,
  onClose,
}: {
  suggestion: Suggestion;
  known: Dish | null;
  onClose: () => void;
}) {
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal">
        <h2>{suggestion.title}</h2>
        <p className="sugg-provenance">
          {known ? `⭐ From your library: ${known.title}` : "✨ New to you"} · ⏱{" "}
          {suggestion.prepTimeMinutes} min · ~{suggestion.estimatedCost} kr
        </p>
        <p>{suggestion.description}</p>
        <h3>Ingredients</h3>
        <ul className="ing-list">
          {suggestion.ingredients.map((ing, i) => (
            <li key={i}>
              <span className="ing-q">{ing.quantity}</span> {ing.name}
            </li>
          ))}
        </ul>
        <div className="modal-actions">
          <button className="btn primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export function PlanWeek({ profile }: { profile: Profile }) {
  const [dishes, setDishes] = useState<Dish[]>([]);
  const [run, setRun] = useState<PlanningRun | null>(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A suggestion open in the Details modal, or null when it's closed.
  const [details, setDetails] = useState<Suggestion | null>(null);
  // The just-for-this-run override, or null when this run uses the defaults.
  const [override, setOverride] = useState<SettingsOverride | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    listDishes()
      .then(setDishes)
      .catch(() => setDishes([]));
  }, []);

  // Switching profiles resets any pending override — it belonged to the person
  // who was on screen, not the one now selected.
  useEffect(() => {
    setOverride(null);
    setEditing(false);
  }, [profile.id]);

  const dishesById = new Map(dishes.map((d) => [d.id, d]));

  // What the next run will actually be planned against: the override when set,
  // otherwise the Profile's saved defaults.
  const defaults = defaultsOf(profile);
  const effective = override ?? defaults;

  // The modal edits a draft in place; storing null when it matches the defaults
  // keeps the chip honest (no "this run" flag when nothing is actually bent).
  function applyDraft(draft: SettingsOverride) {
    setOverride(sameAsDefaults(draft, defaults) ? null : draft);
  }

  async function handlePlan() {
    setPlanning(true);
    setError(null);
    try {
      setRun(await planWeek(profile.id, override ?? undefined));
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setPlanning(false);
    }
  }

  return (
    <section className="plan-week">
      <div className="plan-bar">
        <button
          className="btn primary"
          onClick={handlePlan}
          disabled={planning}
        >
          {planning ? "Asking the model…" : "⚡ Plan my week"}
        </button>
        <button
          className={
            override ? "chip settings-chip overridden" : "chip settings-chip"
          }
          title="Adjust the settings for this run"
          onClick={() => setEditing(true)}
        >
          ⚙ {settingsSummary(effective)}
          {override && <span className="chip-flag"> · this run</span>}
        </button>
      </div>

      {editing && (
        <OverrideModal
          draft={effective}
          defaults={defaults}
          onChange={applyDraft}
          onReset={() => setOverride(null)}
          onClose={() => setEditing(false)}
        />
      )}

      {error && <p className="error">Could not plan: {error}</p>}

      {run && run.status === "partial" && (
        <div className="banner">
          ⚠ Partial plan — asked for {run.requestedDays} days ×{" "}
          {run.requestedSuggestionsPerDay}, the model returned {run.dayCount}.
          <button className="btn" onClick={handlePlan}>
            Try again
          </button>
        </div>
      )}

      {run && run.status === "failed" && (
        <div className="banner error">
          The model couldn't produce a plan this time.
          <button className="btn" onClick={handlePlan}>
            Try again
          </button>
        </div>
      )}

      {run && run.days.length > 0 ? (
        <div className="plan-board">
          {run.days.map((day) => (
            <div className="day-column" key={day.day}>
              <header className="day-head">Day {day.day}</header>
              <div className="day-stack">
                {day.suggestions.map((s, i) => (
                  <SuggestionCard
                    key={i}
                    suggestion={s}
                    dishesById={dishesById}
                    onDetails={() => setDetails(s)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        !planning && (
          <div className="empty-state">
            <p className="muted">
              No plan on screen yet — hit “⚡ Plan my week”.
            </p>
          </div>
        )
      )}

      {details && (
        <DetailsModal
          suggestion={details}
          known={
            details.sourceDish
              ? dishesById.get(details.sourceDish) ?? null
              : null
          }
          onClose={() => setDetails(null)}
        />
      )}
    </section>
  );
}
