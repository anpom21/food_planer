import { useEffect, useState } from "react";
import {
  listDishes,
  planWeek,
  type Dish,
  type PlanningRun,
  type Profile,
  type Suggestion,
} from "./api";

// Issue #23 — Plan a Week: one button, one pass, a board of day columns.
//
// The plan owns the screen. Controls collapse into a top bar so they never
// crowd out the plan: the "⚡ Plan my week" button and a chip summarising the
// settings this run would use. One press fires a single structured LLM call
// that returns the whole week at once, so no dish repeats across days.

function settingsSummary(profile: Profile): string {
  const s = profile.settings;
  return `${s.daysToPlan} days · ${s.suggestionsPerDay}/day`;
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

  useEffect(() => {
    listDishes()
      .then(setDishes)
      .catch(() => setDishes([]));
  }, []);

  const dishesById = new Map(dishes.map((d) => [d.id, d]));

  async function handlePlan() {
    setPlanning(true);
    setError(null);
    try {
      setRun(await planWeek(profile.id));
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
        <span className="chip settings-chip" title="This run's settings">
          ⚙ {settingsSummary(profile)}
        </span>
      </div>

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
