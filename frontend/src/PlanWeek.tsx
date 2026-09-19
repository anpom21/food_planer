import { useEffect, useState } from "react";
import {
  addShoppingItems,
  listDishes,
  planWeek,
  type Dish,
  type PlanningRun,
  type Profile,
  type ShoppingItemInput,
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
//
// Clicking anywhere on the card toggles selection (a filled check circle plus
// an accent ring). Details stops the click reaching the card, so reading about
// a dish never commits you to cooking it — there is no per-card add button.
function SuggestionCard({
  suggestion,
  dishesById,
  selected,
  onToggle,
  onDetails,
}: {
  suggestion: Suggestion;
  dishesById: Map<string, Dish>;
  selected: boolean;
  onToggle: () => void;
  onDetails: () => void;
}) {
  const known = suggestion.sourceDish
    ? dishesById.get(suggestion.sourceDish)
    : null;
  return (
    <article
      className={`sugg-card selectable${selected ? " on" : ""}`}
      onClick={onToggle}
      aria-pressed={selected}
    >
      {selected && (
        <span className="selmark" aria-label="Selected">
          ✓
        </span>
      )}
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
      <button
        className="btn ghost sugg-details"
        onClick={(e) => {
          e.stopPropagation();
          onDetails();
        }}
      >
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

// A selected card, carried in board order (day 1 → day N) into the review. The
// key is pure frontend state — day index + position — never sent to the backend.
type Selected = {
  key: string;
  dayLabel: string;
  suggestion: Suggestion;
};

const cardKey = (dayIndex: number, suggIndex: number) =>
  `${dayIndex}:${suggIndex}`;

const ingKey = (card: string, name: string) => `${card}::${name}`;

const norm = (name: string) => name.toLowerCase().trim();

// A duplicated ingredient's assigned tint (0–5, cycled) and how many selected
// dishes want it.
type Tint = { tint: number; count: number };

// Ingredients wanted by more than one selected dish get a stable tint each (six
// tints, cycled) plus an "in N dishes" label, so overlaps are obvious and the
// redundant copies can be unticked. Keyed by the normalised ingredient name and
// assigned in name order so the same duplicate always lands on the same tint.
function tintMap(selected: Selected[]): Map<string, Tint> {
  const counts = new Map<string, number>();
  for (const s of selected) {
    for (const ing of s.suggestion.ingredients) {
      const k = norm(ing.name);
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
  }
  const map = new Map<string, Tint>();
  let n = 0;
  for (const k of [...counts.keys()].sort()) {
    const count = counts.get(k)!;
    if (count > 1) map.set(k, { tint: n++ % 6, count });
  }
  return map;
}

// The review: every selected dish's ingredients grouped by dish in board order,
// all ticked by default, with the day name and a count per group. Unticking
// greys and strikes the row in place rather than hiding it, so nothing jumps
// around. The confirm button counts what is ticked and disables at zero.
function IngredientReview({
  selected,
  onCancel,
  onConfirm,
}: {
  selected: Selected[];
  onCancel: () => void;
  onConfirm: (items: ShoppingItemInput[]) => void;
}) {
  // "<cardKey>::<ingredient>" → ticked. Built once, all on, when the review opens.
  const [ticked, setTicked] = useState<Record<string, boolean>>(() => {
    const seed: Record<string, boolean> = {};
    for (const s of selected)
      for (const ing of s.suggestion.ingredients)
        seed[ingKey(s.key, ing.name)] = true;
    return seed;
  });

  const tints = tintMap(selected);
  const total = selected.reduce((n, s) => n + s.suggestion.ingredients.length, 0);
  const checked = Object.values(ticked).filter(Boolean).length;

  function setAll(on: boolean) {
    setTicked((prev) => {
      const next: Record<string, boolean> = {};
      for (const k of Object.keys(prev)) next[k] = on;
      return next;
    });
  }

  function confirm() {
    const items: ShoppingItemInput[] = [];
    for (const s of selected) {
      const kind = s.suggestion.sourceDish ? "known" : "unknown";
      for (const ing of s.suggestion.ingredients) {
        if (!ticked[ingKey(s.key, ing.name)]) continue;
        items.push({
          name: ing.name,
          quantity: ing.quantity,
          source: { suggestionTitle: s.suggestion.title, kind },
        });
      }
    }
    onConfirm(items);
  }

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal wide">
        <h2>Add ingredients</h2>
        <p className="review-sub">
          {selected.length} {selected.length === 1 ? "dish" : "dishes"} · {total}{" "}
          ingredients, grouped by dish. Everything starts ticked — untick
          whatever you already have.
          {tints.size > 0 && (
            <>
              <br />
              Tinted rows are the same ingredient wanted by more than one dish.
            </>
          )}
        </p>
        <div className="review-shortcuts">
          <button className="btn ghost" onClick={() => setAll(true)}>
            Select all
          </button>
          <button className="btn ghost" onClick={() => setAll(false)}>
            Deselect all
          </button>
        </div>
        <div className="review-scroll">
          {selected.map((s) => (
            <div className="ing-group" key={s.key}>
              <div className="ing-group-head">
                <span>{s.suggestion.title}</span>
                <span className="muted">
                  {s.dayLabel} · {s.suggestion.ingredients.length} ingredients
                </span>
              </div>
              {s.suggestion.ingredients.map((ing, i) => {
                const k = ingKey(s.key, ing.name);
                const on = !!ticked[k];
                const t = tints.get(norm(ing.name));
                return (
                  <label
                    className={`ing-row${t ? ` tint-${t.tint}` : ""}${
                      on ? "" : " off"
                    }`}
                    key={i}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        setTicked((prev) => ({ ...prev, [k]: !prev[k] }))
                      }
                    />
                    <span className="ing-row-q">{ing.quantity}</span>
                    <span className="ing-row-nm">{ing.name}</span>
                    {t && <span className="ing-row-dup">in {t.count} dishes</span>}
                  </label>
                );
              })}
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn primary" onClick={confirm} disabled={checked === 0}>
            Add {checked} ingredient{checked === 1 ? "" : "s"}
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
  // Card selection — pure frontend state, gone on refresh, never persisted.
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [reviewing, setReviewing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

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
      // A fresh plan replaces the board, so old selections no longer point at
      // anything — start clean.
      setSelectedKeys(new Set());
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setPlanning(false);
    }
  }

  function toggleCard(key: string) {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // Selected cards in board order (day 1 → day N), ready for the review.
  const selected: Selected[] = [];
  run?.days.forEach((day, dayIndex) => {
    day.suggestions.forEach((suggestion, suggIndex) => {
      const key = cardKey(dayIndex, suggIndex);
      if (selectedKeys.has(key))
        selected.push({ key, dayLabel: `Day ${day.day}`, suggestion });
    });
  });

  async function handleConfirm(items: ShoppingItemInput[]) {
    try {
      await addShoppingItems(items);
      setReviewing(false);
      setSelectedKeys(new Set());
      setToast(
        `${items.length} ingredient${items.length === 1 ? "" : "s"} added to the shopping list`,
      );
      setTimeout(() => setToast(null), 2600);
    } catch (e: unknown) {
      setError(String(e));
      setReviewing(false);
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
          {run.days.map((day, dayIndex) => (
            <div className="day-column" key={day.day}>
              <header className="day-head">Day {day.day}</header>
              <div className="day-stack">
                {day.suggestions.map((s, i) => {
                  const key = cardKey(dayIndex, i);
                  return (
                    <SuggestionCard
                      key={i}
                      suggestion={s}
                      dishesById={dishesById}
                      selected={selectedKeys.has(key)}
                      onToggle={() => toggleCard(key)}
                      onDetails={() => setDetails(s)}
                    />
                  );
                })}
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

      {reviewing && (
        <IngredientReview
          selected={selected}
          onCancel={() => setReviewing(false)}
          onConfirm={handleConfirm}
        />
      )}

      {/* While anything is selected, a bottom bar shows the count, a Clear link
          and Add ingredients. There is no per-card add button. */}
      {selected.length > 0 && (
        <div className="select-bar">
          <div className="select-bar-left">
            <strong>
              {selected.length} {selected.length === 1 ? "dish" : "dishes"}{" "}
              selected
            </strong>
            <button
              className="btn ghost"
              onClick={() => setSelectedKeys(new Set())}
            >
              Clear
            </button>
          </div>
          <button className="btn primary" onClick={() => setReviewing(true)}>
            Add ingredients
          </button>
        </div>
      )}

      {toast && <div className="toast">✓ {toast}</div>}
    </section>
  );
}
