import { useCallback, useEffect, useMemo, useState } from "react";
import {
  dishAsSuggestion,
  listDishes,
  listRecipes,
  recipeAsSuggestion,
  type MyWeekEntry,
  type Suggestion,
} from "./api";
import { useMyWeekStore } from "./myWeekStore";
import { Sheet } from "./Sheet";

// My week: the dishes chosen for a week — from the planner's suggestions,
// the household's own dishes or the imported recipes. One week shows at a
// time; the arrows step back through earlier weeks (kept forever) and one
// week ahead. A dish goes in from the plate+ button on any dish card, by
// adding its ingredients, or from the "+ Add dish" tile here.

const DAY_MS = 24 * 60 * 60 * 1000;

// Weeks are named by their Monday as an ISO date; step them as UTC dates so
// summer time never shifts a day.
function shiftWeek(week: string, by: number): string {
  const d = new Date(`${week}T00:00:00Z`);
  return new Date(d.getTime() + by * 7 * DAY_MS).toISOString().slice(0, 10);
}

function weekRange(week: string): string {
  const start = new Date(`${week}T00:00:00Z`);
  const end = new Date(start.getTime() + 6 * DAY_MS);
  const fmt = (d: Date) =>
    d.toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
  return `${fmt(start)} – ${fmt(end)}`;
}

function weekName(week: string, current: string): string {
  if (week === current) return "This week";
  if (week === shiftWeek(current, -1)) return "Last week";
  if (week === shiftWeek(current, 1)) return "Next week";
  return `Week of ${weekRange(week).split(" – ")[0]}`;
}

// The week on screen, over the app-wide My week store. Shared by the My week
// list and the planner below it, so a dish added from the planner shows up
// straight away — and adds from here land in the week on screen.
export function useMyWeek() {
  const { data, error, add: addTo, remove } = useMyWeekStore();
  const [shown, setWeek] = useState<string | null>(null);
  const week = shown ?? data?.currentWeek ?? null;

  const add = useCallback(
    (suggestions: Suggestion[]) => addTo(suggestions, week ?? undefined),
    [addTo, week],
  );

  return { data, week, setWeek, error, add, remove };
}

export type MyWeekState = ReturnType<typeof useMyWeek>;

function WeekCard({
  entry,
  onDetails,
  onIngredients,
  onRemove,
}: {
  entry: MyWeekEntry;
  onDetails: () => void;
  onIngredients: () => void;
  onRemove: () => void;
}) {
  const s = entry.suggestion;
  return (
    <article className="sugg-card week-card">
      <button
        className="week-remove"
        onClick={onRemove}
        aria-label={`Remove ${s.title} from this week`}
        title="Remove from this week"
      >
        ✕
      </button>
      {/* The photo opens Details; only the photo in Details opens the recipe. */}
      {s.recipe?.thumbnail && (
        <button
          className="week-thumb"
          onClick={onDetails}
          aria-label={`${s.title} — show details`}
        >
          <img src={s.recipe.thumbnail} alt="" loading="lazy" />
        </button>
      )}
      <h3 className="sugg-title">{s.title}</h3>
      <div className="sugg-chips">
        {s.recipe ? (
          <span className="chip recipe">📖 {s.recipe.source ?? "Recipe"}</span>
        ) : s.sourceDish ? (
          <span className="chip known">⭐ My dish</span>
        ) : (
          <span className="chip unknown">✨ Suggested</span>
        )}
        {(s.recipe?.totalTime || s.prepTimeMinutes > 0) && (
          <span className="chip">⏱ {s.recipe?.totalTime ?? `${s.prepTimeMinutes} min`}</span>
        )}
        {s.estimatedCost > 0 && <span className="chip">~{s.estimatedCost} kr</span>}
      </div>
      <div className="sugg-actions">
        <button className="btn ghost" onClick={onDetails}>
          Details
        </button>
        <button
          className="btn"
          onClick={onIngredients}
          disabled={s.ingredients.length === 0}
          title={s.ingredients.length === 0 ? "No ingredients written down for this dish" : undefined}
        >
          + Ingredients
        </button>
      </div>
    </article>
  );
}

type Pick = { key: string; label: string; hint: string; suggestion: Suggestion };

// "+ Add dish": one search over the household's own dishes and every imported
// recipe. Tapping a row adds it to the week on screen and keeps the sheet open,
// so a whole week can be filled in one go.
function AddDishSheet({
  inWeek,
  onAdd,
  onClose,
}: {
  inWeek: Set<string>;
  onAdd: (suggestion: Suggestion) => Promise<void>;
  onClose: () => void;
}) {
  const [picks, setPicks] = useState<Pick[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listDishes(), listRecipes()])
      .then(([dishes, recipes]) =>
        setPicks([
          ...dishes.map((d) => ({
            key: `d:${d.id}`,
            label: d.title,
            hint: "⭐ My dish",
            suggestion: dishAsSuggestion(d),
          })),
          ...recipes.map((r) => ({
            key: `r:${r.url}`,
            label: r.title,
            hint: `📖 ${r.recipe?.source ?? "Recipe"}${r.total_time ? ` · ⏱ ${r.total_time}` : ""}`,
            suggestion: recipeAsSuggestion(r),
          })),
        ]),
      )
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return (picks ?? [])
      .filter((p) => words.every((w) => p.label.toLowerCase().includes(w)))
      .slice(0, 40);
  }, [picks, query]);

  return (
    <Sheet title="Add a dish to this week" onClose={onClose}>
      <input
        type="search"
        className="search add-dish-search"
        placeholder="Search your dishes and recipes…"
        value={query}
        autoFocus
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && <p className="error">{error}</p>}
      {picks === null ? (
        <p className="muted">Loading dishes and recipes…</p>
      ) : shown.length === 0 ? (
        <p className="muted">Nothing matches that search.</p>
      ) : (
        <ul className="add-dish-list">
          {shown.map((p) => {
            const added = inWeek.has(p.label.trim().toLowerCase());
            return (
              <li key={p.key}>
                <button
                  className={`add-dish-row${added ? " added" : ""}`}
                  disabled={added}
                  onClick={() => void onAdd(p.suggestion)}
                >
                  {p.suggestion.recipe?.thumbnail ? (
                    <img src={p.suggestion.recipe.thumbnail} alt="" loading="lazy" />
                  ) : (
                    <span className="add-dish-noimg" aria-hidden="true">🍽</span>
                  )}
                  <span className="add-dish-text">
                    <strong>{p.label}</strong>
                    <span className="muted">{p.hint}</span>
                  </span>
                  <span className="add-dish-go">{added ? "✓ Added" : "+ Add"}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Sheet>
  );
}

export function MyWeekPanel({
  state,
  onDetails,
  onIngredients,
}: {
  state: MyWeekState;
  onDetails: (suggestion: Suggestion) => void;
  onIngredients: (suggestion: Suggestion) => void;
}) {
  const { data, week, setWeek, error, add, remove } = state;
  const [adding, setAdding] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  if (!data || !week) {
    return (
      <section className="my-week">
        {error ? <p className="error">Could not load My week: {error}</p> : <p className="muted">Loading…</p>}
      </section>
    );
  }

  const entries = data.entries.filter((e) => e.week === week);
  // Back as far as the oldest week with a dish in it; ahead by one week.
  const oldest = data.entries.reduce((w, e) => (e.week < w ? e.week : w), data.currentWeek);
  const newest = shiftWeek(data.currentWeek, 1);
  const titles = new Set(entries.map((e) => e.suggestion.title.trim().toLowerCase()));

  return (
    <section className="my-week">
      <header className="my-week-head">
        <div>
          <h1>My week</h1>
          <p className="muted">
            {entries.length === 0
              ? "No dishes chosen yet."
              : `${entries.length} ${entries.length === 1 ? "dish" : "dishes"} chosen.`}
          </p>
        </div>
        <div className="week-nav" aria-label="Choose a week">
          <button
            className="icon-btn"
            onClick={() => setWeek(shiftWeek(week, -1))}
            disabled={week <= oldest}
            aria-label="Previous week"
          >
            ‹
          </button>
          <div className="week-nav-label">
            <strong>{weekName(week, data.currentWeek)}</strong>
            <span className="muted">{weekRange(week)}</span>
          </div>
          <button
            className="icon-btn"
            onClick={() => setWeek(shiftWeek(week, 1))}
            disabled={week >= newest}
            aria-label="Next week"
          >
            ›
          </button>
          {week !== data.currentWeek && (
            <button className="link-btn" onClick={() => setWeek(data.currentWeek)}>
              Back to this week
            </button>
          )}
        </div>
      </header>

      {(error || removeError) && <p className="error">{removeError ?? error}</p>}

      <div className="week-grid">
        {entries.map((entry) => (
          <WeekCard
            key={entry.id}
            entry={entry}
            onDetails={() => onDetails(entry.suggestion)}
            onIngredients={() => onIngredients(entry.suggestion)}
            onRemove={() => {
              setRemoveError(null);
              remove(entry).catch((e: unknown) => setRemoveError(String(e)));
            }}
          />
        ))}
        <button className="card add-tile week-add" onClick={() => setAdding(true)}>
          + Add dish
        </button>
      </div>

      {adding && (
        <AddDishSheet
          inWeek={titles}
          onAdd={async (s) => {
            await add([s]);
          }}
          onClose={() => setAdding(false)}
        />
      )}
    </section>
  );
}
