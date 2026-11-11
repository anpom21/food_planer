import { useEffect, useState } from "react";
import { useHousehold } from "./household";
import { PlanningFields } from "./SettingsScreen";
import { Sheet } from "./Sheet";
import { OfferCard, OfferTag, offerFor, runAtSelectedShops } from "./OfferTag";
import { orderedIngredients } from "./ingredientOrder";
import { OnHandBadge } from "./OnHand";
import { RecipeButton, RecipeFacts, RecipeThumb } from "./RecipeLink";
import { MyWeekPanel, useMyWeek } from "./MyWeek";
import { AddToWeekButton } from "./PlatePlus";
import {
  addShoppingItems,
  getFridge,
  getPlanningRun,
  listDishes,
  listPlanningRuns,
  planWeek,
  saveSettings,
  type Dish,
  type PlanningRun,
  type PlanningRunSummary,
  type PlanningSettings,
  type SettingsOverride,
  type ShoppingItemInput,
  type Suggestion,
} from "./api";

// The My week tab: the dishes chosen for the week on top (MyWeek.tsx), and
// below them the planner that suggests more.
//
// Issue #23 — the planner: one button, one pass, a board of day columns.
// Controls collapse into a top bar so they never crowd out the plan: the
// "⚡ Suggest dishes" button and a chip summarising the
// settings this run would use. One press fires a single structured LLM call
// that returns the whole week at once, so no dish repeats across days.
//
// Issue #25, reworked — ⚡ Suggest dishes opens a sheet with every planning
// setting (days, the known-vs-unknown lean, priorities, shops, online recipes,
// Inspiration), starting from the saved defaults, and plans from there. "Keep
// as my defaults" saves them first; unticked, they're sent as an override for
// this run only and never written back, so planning a short week never means
// editing (and forgetting to restore) your defaults.

const PLANNING_KEYS = [
  "daysToPlan",
  "suggestionsPerDay",
  "knownVsUnknownBias",
  "priority",
  "shops",
  "inspiration",
  "recipeMode",
] as const;

function sameSettings(a: PlanningSettings, b: PlanningSettings): boolean {
  return PLANNING_KEYS.every((k) => JSON.stringify(a[k]) === JSON.stringify(b[k]));
}

function biasWord(bias: number): string {
  if (bias <= 0.34) return "mostly known";
  if (bias >= 0.66) return "mostly new";
  return "a mix";
}

function settingsSummary(s: PlanningSettings): string {
  return `${s.daysToPlan} days · ${s.suggestionsPerDay}/day · ${biasWord(
    s.knownVsUnknownBias,
  )}`;
}

function SuggestSheet({
  initial,
  defaults,
  onSuggest,
  onClose,
}: {
  initial: PlanningSettings;
  defaults: PlanningSettings;
  // Resolves once the settings are saved (when kept) and planning has begun.
  onSuggest: (settings: PlanningSettings, keep: boolean) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<PlanningSettings>(initial);
  const [keep, setKeep] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bent = !sameSettings(draft, defaults);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSuggest(draft, keep && bent);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Sheet title="Suggest dishes" onClose={onClose}>
      <form className="settings suggest-sheet" onSubmit={submit}>
        <p className="muted">
          What should this plan go for? It starts from your saved defaults.
        </p>
        <PlanningFields
          draft={draft}
          onChange={(fields) => setDraft((prev) => ({ ...prev, ...fields }))}
        />
        <div className="settings-actions suggest-actions">
          {bent ? (
            <label className="keep-defaults">
              <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
              Keep as my defaults
            </label>
          ) : (
            <span className="muted keep-defaults">Your saved defaults</span>
          )}
          {bent && (
            <button type="button" className="link-btn" onClick={() => setDraft(defaults)}>
              Reset
            </button>
          )}
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Starting…" : "⚡ Suggest dishes"}
          </button>
          {error && <span className="error">{error}</span>}
        </div>
      </form>
    </Sheet>
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
        {suggestion.recipe ? (
          <span className="chip recipe">📖 {suggestion.recipe.source ?? "Recipe"}</span>
        ) : suggestion.sourceDish ? (
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
        <AddToWeekButton suggestion={suggestion} className="inline" />
      </div>
    </article>
  );
}

// Details opens the full suggestion — the description in full and the ingredient
// list that the card deliberately withholds.
export function DetailsModal({
  suggestion,
  known,
  onClose,
  onAddIngredients,
}: {
  suggestion: Suggestion;
  known: Dish | null;
  onClose: () => void;
  // When given, a "+ Ingredients" button at the bottom adds this dish's
  // ingredients to the shopping list (and the dish to My week).
  onAddIngredients?: () => void;
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
          {suggestion.recipe
            ? `📖 Recipe from ${suggestion.recipe.source ?? "the web"}`
            : known
              ? `⭐ From your library: ${known.title}`
              : "✨ New to you"}{" "}
          · ⏱{" "}
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
        {orderedIngredients(suggestion).map((group) => (
          <div key={group.heading ?? ""}>
            {group.heading && <h4 className="ing-subhead">{group.heading}</h4>}
            <ul className="ing-list">
              {group.rows.map(({ ingredient: ing, offer }, i) => (
                <li key={i}>
                  <span className="ing-q">{ing.quantity}</span> {ing.name}
                  <OnHandBadge have={ing.have} />
                  {offer && <OfferTag offer={offer} />}
                </li>
              ))}
            </ul>
          </div>
        ))}
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
          <button className="btn" onClick={onClose}>
            Close
          </button>
          {onAddIngredients && (
            <button
              className="btn primary"
              onClick={onAddIngredients}
              disabled={suggestion.ingredients.length === 0}
            >
              + Ingredients
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// A selected card, carried in board order (day 1 → day N) into the review. The
// key is pure frontend state — day index + position — never sent to the backend.
export type Selected = {
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
export function IngredientReview({
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
        const offer = offerFor(ing, s.suggestion.discounts);
        items.push({
          name: ing.name,
          quantity: ing.quantity,
          source: { suggestionTitle: s.suggestion.title, kind },
          // Keep the shop: the list groups by it and the exports name it.
          offer: offer && {
            shop: offer.shop,
            shopSlug: offer.shopSlug ?? null,
            productName: offer.productName,
            price: offer.price,
          },
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
              {orderedIngredients(s.suggestion).flatMap((group) => [
                group.heading && (
                  <div className="ing-subhead" key={`h:${group.heading}`}>
                    {group.heading}
                  </div>
                ),
                ...group.rows.map(({ ingredient: ing, offer }, i) => {
                  const k = ingKey(s.key, ing.name);
                  const on = !!ticked[k];
                  const t = tints.get(norm(ing.name));
                  return (
                    <label
                      className={`ing-row${t ? ` tint-${t.tint}` : ""}${
                        on ? "" : " off"
                      }`}
                      key={`${group.heading ?? ""}:${i}`}
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
                      {offer && <OfferTag offer={offer} />}
                      {t && <span className="ing-row-dup">in {t.count} dishes</span>}
                    </label>
                  );
                }),
              ])}
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
// browsable forever, newest first.
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
          <p className="muted">No plans yet — hit “⚡ Suggest dishes”.</p>
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
                      {r.dayCount}{" "}
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

export function PlanWeek() {
  const { settings, setSettings, go, notify, openSettings, refreshCounts } = useHousehold();
  const [freshCount, setFreshCount] = useState<number | null>(null);
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
  // The settings the last plan used when they weren't the saved defaults, so
  // Try again and the next sheet start from them; null means the defaults.
  const [override, setOverride] = useState<PlanningSettings | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  // Card selection — pure frontend state, gone on refresh, never persisted.
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [reviewing, setReviewing] = useState(false);
  // The Past-plans archive modal (issue #26).
  const [browsing, setBrowsing] = useState(false);
  // My week, shown above the planner; picks from the planner land in it.
  const week = useMyWeek();
  // One dish whose ingredients are being reviewed (from My week or Details).
  const [addingOne, setAddingOne] = useState<Suggestion | null>(null);

  useEffect(() => {
    listDishes()
      .then(setDishes)
      .catch(() => setDishes([]));
    getFridge()
      .then((f) => setFreshCount(f.fresh.length))
      .catch(() => setFreshCount(null));
  }, []);

  const dishesById = new Map(dishes.map((d) => [d.id, d]));

  // What the next run will actually be planned against: the override when set,
  // otherwise the household's saved defaults.
  const effective = override ?? settings;

  // From the sheet: save the settings as the defaults if asked, then plan with
  // them. Storing null when they match the defaults keeps the chip honest (no
  // "this run" flag when nothing is actually bent).
  async function suggestWith(chosen: PlanningSettings, keep: boolean) {
    let next: PlanningSettings | null = sameSettings(chosen, settings) ? null : chosen;
    if (keep) {
      setSettings(await saveSettings(chosen));
      next = null;
    }
    setOverride(next);
    setSuggesting(false);
    void handlePlan(next);
  }

  async function handlePlan(withSettings: PlanningSettings | null = override) {
    setPlanning(true);
    setError(null);
    try {
      const runOverride: SettingsOverride | undefined = withSettings
        ? Object.fromEntries(PLANNING_KEYS.map((k) => [k, withSettings[k]]))
        : undefined;
      setRun(await planWeek(runOverride));
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

  // What the board shows: the run, with offers only from the shops it's being
  // planned for right now (the stored run keeps them all).
  const board = run && runAtSelectedShops(run, effective.shops);

  // Selected cards in board order (day 1 → day N), ready for the review.
  const selected: Selected[] = [];
  board?.days.forEach((day, dayIndex) => {
    day.suggestions.forEach((suggestion, suggIndex) => {
      const key = cardKey(dayIndex, suggIndex);
      if (selectedKeys.has(key))
        selected.push({ key, dayLabel: `Day ${day.day}`, suggestion });
    });
  });

  // Adding a dish's ingredients also puts the dish in My week.
  async function addIngredients(items: ShoppingItemInput[], dishes: Suggestion[]) {
    await addShoppingItems(items);
    const created = await week.add(dishes);
    refreshCounts();
    notify(
      `${items.length} ingredient${items.length === 1 ? "" : "s"} added` +
        (created ? " · in My week" : ""),
      { label: "View list", run: () => go("shopping") },
    );
  }

  async function handleConfirm(items: ShoppingItemInput[]) {
    try {
      await addIngredients(items, selected.map((s) => s.suggestion));
      setReviewing(false);
      setSelectedKeys(new Set());
    } catch (e: unknown) {
      setError(String(e));
      setReviewing(false);
    }
  }

  async function handleConfirmOne(items: ShoppingItemInput[]) {
    const dish = addingOne!;
    setAddingOne(null);
    try {
      await addIngredients(items, [dish]);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  return (
    <section className="plan-week">
      <MyWeekPanel state={week} onDetails={setDetails} onIngredients={setAddingOne} />

      <header className="planner-head">
        <h2>Suggestions</h2>
        <p className="muted">
          Let the planner suggest dishes from your fridge, this week's offers and
          your dishes. Pick some and add their ingredients — they go into My week.
        </p>
      </header>
      <div className="plan-bar">
        <button
          className="btn primary"
          onClick={() => setSuggesting(true)}
          disabled={planning}
        >
          {planning ? `Asking the model… ${elapsed}s` : "⚡ Suggest dishes"}
        </button>
        <button
          className={
            override ? "chip settings-chip overridden" : "chip settings-chip"
          }
          title="Adjust the settings and suggest dishes"
          disabled={planning}
          onClick={() => setSuggesting(true)}
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

      {suggesting && (
        <SuggestSheet
          initial={effective}
          defaults={settings}
          onSuggest={suggestWith}
          onClose={() => setSuggesting(false)}
        />
      )}

      {error && <p className="error">Could not plan: {error}</p>}

      {run && run.status === "partial" && (
        <div className="banner">
          ⚠ Partial plan — asked for {run.requestedDays} days ×{" "}
          {run.requestedSuggestionsPerDay}, the model returned {run.dayCount}.
          <button className="btn" onClick={() => void handlePlan()}>
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
          <button className="btn" onClick={() => void handlePlan()}>
            Try again
          </button>
        </div>
      )}

      {board && board.days.length > 0 ? (
        <div className="plan-board">
          {board.days.map((day, dayIndex) => (
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
          // What the next plan will be made from, each one a tap from where
          // it's changed — so the tabs read as one flow, not four screens.
          <div className="plan-ready">
            <h2>Ready when you are</h2>
            <p className="muted">
              The plan is made from what's in your fridge, this week's offers at
              your shops, your own dishes and online recipes.
            </p>
            <ul className="ready-list">
              <li>
                <button className="ready-row" onClick={() => go("fridge")}>
                  <span className="ready-icon">🥬</span>
                  <span>
                    <strong>{freshCount ?? "…"} fresh items</strong>
                    <span className="muted"> to use up first</span>
                  </span>
                  <span className="ready-go" aria-hidden="true">›</span>
                </button>
              </li>
              <li>
                <button className="ready-row" onClick={() => openSettings("planning")}>
                  <span className="ready-icon">🏷️</span>
                  <span>
                    <strong>
                      {settings.shops.length} {settings.shops.length === 1 ? "shop" : "shops"}
                    </strong>
                    <span className="muted"> for offers</span>
                  </span>
                  <span className="ready-go" aria-hidden="true">›</span>
                </button>
              </li>
              <li>
                <button className="ready-row" onClick={() => go("dishes")}>
                  <span className="ready-icon">🍲</span>
                  <span>
                    <strong>{dishes.length} of your dishes</strong>
                    <span className="muted">
                      {" "}
                      ·{" "}
                      {settings.recipeMode === "only"
                        ? "only online recipes"
                        : settings.recipeMode === "none"
                          ? "no online recipes"
                          : "plus online recipes"}
                    </span>
                  </span>
                  <span className="ready-go" aria-hidden="true">›</span>
                </button>
              </li>
            </ul>
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
          onAddIngredients={() => {
            setAddingOne(details);
            setDetails(null);
          }}
        />
      )}

      {addingOne && (
        <IngredientReview
          selected={[{ key: "one", dayLabel: "My week", suggestion: addingOne }]}
          onCancel={() => setAddingOne(null)}
          onConfirm={(items) => void handleConfirmOne(items)}
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

    </section>
  );
}
