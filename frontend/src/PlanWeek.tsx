import { useEffect, useState } from "react";
import { BiasSlider, Stepper } from "./SettingsScreen";
import { OfferCard, OfferTag, offerFor } from "./OfferTag";
import { OnHandBadge } from "./OnHand";
import { RecipeButton, RecipeFacts, RecipeThumb } from "./RecipeLink";
import {
  addShoppingItems,
  getPlanningRun,
  listDishes,
  listPlanningRuns,
  planWeek,
  type Dish,
  type PlanningRun,
  type PlanningRunSummary,
  type Profile,
  type SettingsOverride,
  type ShoppingItemInput,
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
        <BiasSlider
          id="override-bias"
          value={draft.knownVsUnknownBias}
          onChange={(knownVsUnknownBias) =>
            onChange({ ...draft, knownVsUnknownBias })
          }
        />
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
      {suggestion.recipe && <RecipeThumb recipe={suggestion.recipe} />}
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
        <span
          className="chip"
          title={
            suggestion.recipe?.workTime
              ? `Arbejdstid ${suggestion.recipe.workTime}`
              : undefined
          }
        >
          ⏱ {suggestion.recipe?.totalTime ?? `${suggestion.prepTimeMinutes} min`}
        </span>
        {suggestion.recipe?.servings && (
          <span className="chip">👥 {suggestion.recipe.servings}</span>
        )}
        <span className="chip">~{suggestion.estimatedCost} kr</span>
        {suggestion.discounts.length > 0 && (
          <span className="chip discount">
            🏷️ {suggestion.discounts.length} on offer
          </span>
        )}
      </div>
      <div className="sugg-actions">
        <button
          className="btn ghost sugg-details"
          onClick={(e) => {
            e.stopPropagation();
            onDetails();
          }}
        >
          Details
        </button>
        {suggestion.recipe && <RecipeButton recipe={suggestion.recipe} />}
      </div>
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
        {suggestion.recipe && (
          <>
            <RecipeThumb recipe={suggestion.recipe} />
            <RecipeFacts recipe={suggestion.recipe} />
          </>
        )}
        <p>{suggestion.description}</p>
        <h3>Ingredients</h3>
        <ul className="ing-list">
          {suggestion.ingredients.map((ing, i) => {
            const offer = offerFor(ing, suggestion.discounts);
            return (
              <li key={i}>
                <span className="ing-q">{ing.quantity}</span> {ing.name}
                <OnHandBadge have={ing.have} />
                {offer && <OfferTag offer={offer} />}
              </li>
            );
          })}
        </ul>
        {suggestion.discounts.length > 0 && (
          <>
            <h3>On offer this week</h3>
            <div className="offer-strip">
              {suggestion.discounts.map((d) => (
                <OfferCard key={d.offerId} offer={d} />
              ))}
            </div>
          </>
        )}
        <div className="modal-actions">
          {suggestion.recipe && <RecipeButton recipe={suggestion.recipe} />}
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
  // "<cardKey>::<ingredient>" → ticked. Built once when the review opens:
  // everything on except pantry staples, which are always in the house.
  // Fresh items stay ticked but marked — there may not be enough left.
  const [ticked, setTicked] = useState<Record<string, boolean>>(() => {
    const seed: Record<string, boolean> = {};
    for (const s of selected)
      for (const ing of s.suggestion.ingredients)
        seed[ingKey(s.key, ing.name)] = ing.have !== "staple";
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
          ingredients, grouped by dish. Everything starts ticked except
          pantry staples (🫙) — untick whatever else you already have, like
          what's in the fridge (🥬).
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
                    <OnHandBadge have={ing.have} />
                    {(() => {
                      const offer = offerFor(ing, s.suggestion.discounts);
                      return offer && <OfferTag offer={offer} />;
                    })()}
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

// A run's status as a short word + tint, so failed and partial runs read as
// themselves in the archive — the app never silently swallows a request.
const STATUS_LABEL: Record<PlanningRunSummary["status"], string> = {
  success: "✓ Complete",
  partial: "⚠ Partial",
  failed: "✕ Failed",
};

// A readable local timestamp; falls back to the raw ISO string if unparseable.
function formatWhen(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });
}

// Issue #26 — Past plans: every run the household has ever made stays
// browsable forever, household-wide (not just this Profile's), newest first.
// Each row carries enough — when, how many days, its status, and the fridge
// notes it was planned against — to find the run you mean without opening each
// one. Picking a row loads that run onto the board.
function ArchiveModal({
  onPick,
  onClose,
}: {
  onPick: (id: string) => void;
  onClose: () => void;
}) {
  const [runs, setRuns] = useState<PlanningRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPlanningRuns()
      .then(setRuns)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal wide">
        <h2>🕘 Past plans</h2>
        <p className="review-sub">
          Every plan the household has made, newest first. Pick one to load it
          onto the board.
        </p>
        {error && <p className="error">Could not load past plans: {error}</p>}
        {runs && runs.length === 0 && (
          <p className="muted">No plans yet — hit “⚡ Plan my week”.</p>
        )}
        {runs && runs.length > 0 && (
          <div className="review-scroll">
            <ul className="archive-list">
              {runs.map((r) => (
                <li key={r.id}>
                  <button
                    className="archive-row"
                    onClick={() => onPick(r.id)}
                  >
                    <div className="archive-row-top">
                      <span className="archive-when">
                        {formatWhen(r.createdAt)}
                      </span>
                      <span className={`chip status-${r.status}`}>
                        {STATUS_LABEL[r.status]}
                      </span>
                    </div>
                    <div className="archive-row-meta muted">
                      {r.profileName} · {r.dayCount}{" "}
                      {r.dayCount === 1 ? "day" : "days"}
                    </div>
                    <div className="archive-fridge muted">
                      {r.fridgeSnippet
                        ? `🧊 ${r.fridgeSnippet}`
                        : "🧊 No fresh items"}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
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
  // Seconds since "Plan my week" was pressed, so a slow run reads as working
  // rather than stuck.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!planning) return;
    setElapsed(0);
    const started = Date.now();
    const tick = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(tick);
  }, [planning]);
  const [error, setError] = useState<string | null>(null);
  // A suggestion open in the Details modal, or null when it's closed.
  const [details, setDetails] = useState<Suggestion | null>(null);
  // The just-for-this-run override, or null when this run uses the defaults.
  const [override, setOverride] = useState<SettingsOverride | null>(null);
  const [editing, setEditing] = useState(false);
  // Card selection — pure frontend state, gone on refresh, never persisted.
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [reviewing, setReviewing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  // The Past-plans archive modal (issue #26).
  const [browsing, setBrowsing] = useState(false);

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
      // A fresh plan replaces the board, so old selections no longer point at
      // anything — start clean.
      setSelectedKeys(new Set());
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setPlanning(false);
    }
  }

  // Load an archived run onto the board. It replaces the current plan, so any
  // selection (which pointed at the old board) is cleared, exactly as a fresh
  // plan does.
  async function loadRun(id: string) {
    setError(null);
    try {
      setRun(await getPlanningRun(id));
      setSelectedKeys(new Set());
      setBrowsing(false);
    } catch (e: unknown) {
      setError(String(e));
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
          {planning ? `Asking the model… ${elapsed}s` : "⚡ Plan my week"}
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
        <button
          className="chip settings-chip"
          title="Browse every plan the household has made"
          onClick={() => setBrowsing(true)}
        >
          🕘 Past plans
        </button>
      </div>

      {browsing && (
        <ArchiveModal onPick={loadRun} onClose={() => setBrowsing(false)} />
      )}

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

      {run && (run.offersUnavailable?.length ?? 0) > 0 && (
        <div className="banner">
          🏷️ Couldn't fetch the tilbudsavis for{" "}
          {run.offersUnavailable!.join(", ")} — this plan was made without
          those offers.
        </div>
      )}

      {run && run.status === "failed" && (
        <div className="banner error">
          The model couldn't produce a plan this time
          {run.error ? ` (${run.error})` : ""}.
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
