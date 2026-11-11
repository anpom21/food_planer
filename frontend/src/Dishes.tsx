import { useEffect, useMemo, useState } from "react";
import {
  addShoppingItems,
  createDish,
  dishAsSuggestion,
  listDishes,
  listRecipeMatches,
  listRecipes,
  recipeAsSuggestion,
  type Dish,
  type Recipe,
  type RecipeMatch,
  type ShoppingItemInput,
  type Suggestion,
} from "./api";
import { useHousehold } from "./household";
import { dishMatches, MyDishes } from "./MyDishes";
import { atSelectedShops } from "./OfferTag";
import { DetailsModal, IngredientReview } from "./PlanWeek";
import { useMyWeekStore } from "./myWeekStore";
import { AddToWeekButton } from "./PlatePlus";
import "./recipes.css";

// The Dishes tab: the household's own dishes and the imported online recipes
// in one place, behind one search. Three views:
//
// - This week — the dinner recipes that use something in the fridge or on
//   offer, ranked the way the planner ranks them (what it plans from);
// - My dishes — the household's library, the meals it already knows;
// - All recipes — every imported recipe.
//
// A recipe card reads like a planned dish — a rough price, and how many of its
// ingredients are already in the fridge, in the pantry, or on offer — and
// opens the same Details and Add-ingredients views as the plan — tapping its
// photo opens Details, whose photo links to the recipe site (the only link
// out; there's no separate "go to recipe" button). ☆ saves a
// recipe into My dishes, and the plate+ next to it puts it in My week, as
// adding its ingredients does too. The grid renders a page at a time (there are ~1800
// recipes) behind a "Show more" button.

const PAGE = 60;

type View = "week" | "mine" | "all";

const VIEWS: { view: View; label: string }[] = [
  { view: "week", label: "This week" },
  { view: "mine", label: "My dishes" },
  { view: "all", label: "All recipes" },
];

function recipeMatchesQuery(recipe: Recipe, needle: string): boolean {
  if (!needle) return true;
  const haystack = [recipe.title, ...recipe.categories, ...recipe.ingredients.map((i) => i.text)]
    .join("\n")
    .toLowerCase();
  return needle
    .toLowerCase()
    .split(/\s+/)
    .every((word) => haystack.includes(word));
}

// A recipe saved into the library: its lines as the ingredients, and a link
// back so the full method is one tap away.
function recipeAsDish(recipe: Recipe) {
  return {
    title: recipe.title,
    ingredients: recipe.ingredients.map((i) => i.text).join("\n"),
    substitutes: null,
    recipe: [recipe.description, recipe.url].filter(Boolean).join("\n\n"),
    favourite: false,
  };
}

function RecipeCard({
  recipe,
  saved,
  onDetails,
  onAdd,
  onSave,
}: {
  recipe: Recipe;
  saved: boolean;
  onDetails: () => void;
  onAdd: () => void;
  onSave: () => void;
}) {
  const { fresh, staple, offers } = recipe.counts;
  return (
    <article className="recipe-card">
      {/* The photo opens Details; the photo in Details goes to the recipe. */}
      <button
        className="recipe-thumb"
        onClick={onDetails}
        aria-label={`${recipe.title} — show details`}
      >
        {recipe.thumbnail ? (
          <img src={recipe.thumbnail} alt="" loading="lazy" />
        ) : (
          <span className="recipe-thumb-empty">No image</span>
        )}
      </button>
      <div className="card-corner">
        <AddToWeekButton suggestion={recipeAsSuggestion(recipe)} />
        <button
          className={`recipe-save${saved ? " on" : ""}`}
          onClick={onSave}
          disabled={saved}
          aria-label={saved ? "In my dishes" : "Save to my dishes"}
          title={saved ? "In my dishes" : "Save to my dishes"}
        >
          {saved ? "★" : "☆"}
        </button>
      </div>
      <div className="recipe-body">
        <h2 className="card-title">{recipe.title}</h2>
        <div className="sugg-chips">
          {recipe.total_time && <span className="chip">⏱ {recipe.total_time}</span>}
          <span
            className="chip"
            title="Rough: the offer price where an ingredient is on offer, ~20 kr for anything else you'd buy"
          >
            ~{recipe.estimatedCost} kr
          </span>
          <span className="chip have-fresh" title="Ingredients in the fridge">
            🥬 {fresh}
          </span>
          <span className="chip have-staple" title="Ingredients in the pantry">
            🫙 {staple}
          </span>
          {offers > 0 && (
            <span className="chip discount" title="Ingredients on offer at your shops">
              🏷️ {offers}
            </span>
          )}
        </div>
        {/* Details (whose photo links to the recipe site), then the main action. */}
        <div className="recipe-actions">
          <button className="btn ghost" onClick={onDetails}>
            Details
          </button>
          <button className="btn primary" onClick={onAdd}>
            + Ingredients
          </button>
        </div>
      </div>
    </article>
  );
}

export function Dishes() {
  const { settings, notify, go, refreshCounts } = useHousehold();
  const myWeek = useMyWeekStore();
  const [view, setView] = useState<View>("week");
  const [dishes, setDishes] = useState<Dish[] | null>(null);
  const [recipes, setRecipes] = useState<Recipe[] | null>(null);
  const [matched, setMatched] = useState<RecipeMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);
  // A recipe or library dish open in Details, or whose ingredients are being
  // added — both shaped as Suggestions.
  const [details, setDetails] = useState<Suggestion | null>(null);
  const [adding, setAdding] = useState<Suggestion | null>(null);

  useEffect(() => {
    listDishes()
      .then(setDishes)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  // Each recipe view is fetched on its first visit: both pull this week's offers.
  useEffect(() => {
    if (view === "all" && recipes === null)
      listRecipes()
        .then(setRecipes)
        .catch((e: unknown) => setError(String(e)));
    if (view === "week" && matched === null)
      listRecipeMatches()
        .then(setMatched)
        .catch((e: unknown) => setError(String(e)));
  }, [view, recipes, matched]);

  // Offers only from shops selected in settings right now; the counts follow.
  const loaded: Recipe[] | null = view === "week" ? matched : view === "all" ? recipes : null;
  const cards = useMemo(
    () =>
      loaded
        ?.filter((r) => recipeMatchesQuery(r, query.trim()))
        .map((r) => {
          const visible = atSelectedShops(r, settings.shops);
          return { ...visible, counts: { ...r.counts, offers: visible.discounts.length } };
        }) ?? null,
    [loaded, query, settings.shops],
  );

  const savedTitles = new Set((dishes ?? []).map((d) => d.title.toLowerCase()));

  async function saveRecipe(recipe: Recipe) {
    try {
      const dish = await createDish(recipeAsDish(recipe));
      setDishes((prev) => [...(prev ?? []), dish]);
      notify(`Saved “${recipe.title}” to my dishes`, {
        label: "View",
        run: () => switchView("mine"),
      });
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  // Adding a dish's ingredients also puts the dish in this week's My week.
  async function handleAdd(items: ShoppingItemInput[]) {
    const dish = adding!;
    try {
      await addShoppingItems(items);
      setAdding(null);
      const created = await myWeek.add([dish]);
      refreshCounts();
      notify(
        `${items.length} ingredient${items.length === 1 ? "" : "s"} added` +
          (created ? " · in My week" : ""),
        { label: "View list", run: () => go("shopping") },
      );
    } catch (e: unknown) {
      setError(String(e));
      setAdding(null);
    }
  }

  function switchView(next: View) {
    setView(next);
    setShown(PAGE);
  }

  const mineShown = (dishes ?? []).filter((d) => dishMatches(d, query)).length;
  const subtitle =
    view === "mine"
      ? `${dishes?.length ?? "…"} dishes you know how to make — the planner picks from these first.`
      : view === "week"
        ? settings.recipeMode === "none"
          ? "Recipes that use your fridge or this week's offers. Online recipes are switched off for planning."
          : "Recipes that use your fridge or this week's offers — what the planner picks from."
        : `${recipes?.length ?? "…"} recipes imported from the web.`;

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1>Dishes</h1>
          <p className="muted">{subtitle}</p>
        </div>
      </header>

      <div className="page-tools">
        <div className="segmented" role="tablist" aria-label="Which dishes">
          {VIEWS.map(({ view: v, label }) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              className={view === v ? "on" : ""}
              onClick={() => switchView(v)}
            >
              {label}
              {v === "mine" && dishes ? <span className="seg-count">{dishes.length}</span> : null}
            </button>
          ))}
        </div>
        <input
          type="search"
          className="search"
          placeholder={view === "mine" ? "Search my dishes…" : "Search title, category, ingredient…"}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShown(PAGE);
          }}
        />
      </div>

      {error && <p className="error">Could not load dishes: {error}</p>}

      {view === "mine" ? (
        dishes === null ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            {query && <p className="muted result-count">{mineShown} of {dishes.length}</p>}
            <MyDishes
              dishes={dishes}
              query={query}
              onChange={setDishes}
              onAddIngredients={(dish) => setAdding(dishAsSuggestion(dish))}
            />
          </>
        )
      ) : cards === null ? (
        <p className="muted">Finding recipes for your fridge and this week's offers…</p>
      ) : cards.length === 0 ? (
        <div className="empty-state stacked">
          <p className="muted">
            {query
              ? "Nothing matches that search."
              : view === "week"
                ? "No recipes use what's in your fridge or on offer right now."
                : "No recipes imported yet. Run uv run food-planer-recipes valdemarsro."}
          </p>
          {!query && view === "week" && (
            <button className="btn" onClick={() => go("fridge")}>
              Add what's in the fridge
            </button>
          )}
        </div>
      ) : (
        <>
          {query && <p className="muted result-count">{cards.length} matches</p>}
          <div className="grid">
            {cards.slice(0, shown).map((recipe) => (
              <RecipeCard
                key={recipe.url}
                recipe={recipe}
                saved={savedTitles.has(recipe.title.toLowerCase())}
                onDetails={() => setDetails(recipeAsSuggestion(recipe))}
                onAdd={() => setAdding(recipeAsSuggestion(recipe))}
                onSave={() => void saveRecipe(recipe)}
              />
            ))}
          </div>
          {shown < cards.length && (
            <div className="show-more">
              <button className="btn" onClick={() => setShown((n) => n + PAGE)}>
                Show more ({cards.length - shown} left)
              </button>
            </div>
          )}
        </>
      )}

      {details && (
        <DetailsModal
          suggestion={details}
          known={null}
          onClose={() => setDetails(null)}
          onAddIngredients={() => {
            setAdding(details);
            setDetails(null);
          }}
        />
      )}
      {adding && (
        <IngredientReview
          selected={[{ key: "one", dayLabel: "My week", suggestion: adding }]}
          onCancel={() => setAdding(null)}
          onConfirm={(items) => void handleAdd(items)}
        />
      )}
    </section>
  );
}
