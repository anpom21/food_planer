import { useEffect, useMemo, useState } from "react";
import {
  addShoppingItems,
  listRecipeMatches,
  listRecipes,
  recipeAsSuggestion,
  type Profile,
  type Recipe,
  type RecipeMatch,
  type ShoppingItemInput,
} from "./api";
import { DetailsModal, IngredientReview } from "./PlanWeek";
import "./recipes.css";

// The Inspiration screen: every imported recipe as a card grid. Each card reads
// like a planned dish — a rough price, and how many of its ingredients are
// already in the fridge, in the pantry, or on offer this week — and opens the
// same Details and Add-ingredients views as the plan. The thumbnail and "Gå til
// opskrift" link to the recipe on its own site. A search matches title,
// category or any ingredient. There are ~1800 recipes, so the grid renders a
// page at a time behind a "Vis flere" button rather than all at once.
//
// The "Til ugens madplan" view shows what the planner works from instead: only
// the dinner recipes that use a fresh item from the Fridge or one of this
// week's offers, ranked the way the planner ranks them.

const PAGE = 60;

type View = "matches" | "all";

function matches(recipe: Recipe, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    recipe.title,
    ...recipe.categories,
    ...recipe.ingredients.map((i) => i.text),
  ]
    .join("\n")
    .toLowerCase();
  return needle
    .toLowerCase()
    .split(/\s+/)
    .every((word) => haystack.includes(word));
}

function RecipeCard({
  recipe,
  onDetails,
  onAdd,
}: {
  recipe: Recipe;
  onDetails: () => void;
  onAdd: () => void;
}) {
  const { fresh, staple, offers } = recipe.counts;
  return (
    <article className="recipe-card">
      <a
        className="recipe-thumb"
        href={recipe.url}
        target="_blank"
        rel="noreferrer"
        aria-label={`${recipe.title} (åbner opskriften)`}
      >
        {recipe.thumbnail ? (
          <img src={recipe.thumbnail} alt="" loading="lazy" />
        ) : (
          <span className="recipe-thumb-empty">Intet billede</span>
        )}
      </a>
      <div className="recipe-body">
        <h2 className="card-title">{recipe.title}</h2>
        <div className="sugg-chips">
          {recipe.total_time && <span className="chip">⏱ {recipe.total_time}</span>}
          <span
            className="chip"
            title="Groft skøn: tilbudspris hvor varen er på tilbud, ellers ~20 kr pr. vare du mangler"
          >
            ~{recipe.estimatedCost} kr
          </span>
          <span className="chip have-fresh" title="Ingredienser du har i køleskabet">
            🥬 {fresh} i køleskabet
          </span>
          <span className="chip have-staple" title="Ingredienser du har i skabet">
            🫙 {staple} i skabet
          </span>
          {offers > 0 && (
            <span className="chip discount" title="Ingredienser på tilbud i dine butikker">
              🏷️ {offers} på tilbud
            </span>
          )}
        </div>
        <div className="sugg-actions">
          <button className="btn ghost" onClick={onDetails}>
            Show details
          </button>
          <button className="btn ghost" onClick={onAdd}>
            Add ingredients
          </button>
        </div>
        <a
          className="btn primary recipe-link"
          href={recipe.url}
          target="_blank"
          rel="noreferrer"
        >
          Gå til opskrift
        </a>
      </div>
    </article>
  );
}

export function Recipes({ profile }: { profile: Profile }) {
  const [view, setView] = useState<View>("matches");
  const [recipes, setRecipes] = useState<Recipe[] | null>(null);
  const [matched, setMatched] = useState<RecipeMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [details, setDetails] = useState<Recipe | null>(null);
  const [adding, setAdding] = useState<Recipe | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Each view is fetched on its first visit: both pull this week's offers.
  useEffect(() => {
    if (view === "all" && recipes === null)
      listRecipes(profile.id).then(setRecipes).catch((e: unknown) => setError(String(e)));
    if (view === "matches" && matched === null)
      listRecipeMatches(profile.id)
        .then(setMatched)
        .catch((e: unknown) => setError(String(e)));
  }, [view, recipes, matched, profile.id]);

  const source: Recipe[] | null = view === "matches" ? matched : recipes;
  const filtered = useMemo(
    () => (source ?? []).filter((r) => matches(r, query.trim())),
    [source, query],
  );

  const switchView = (next: View) => {
    setView(next);
    setShown(PAGE);
  };

  async function handleAdd(items: ShoppingItemInput[]) {
    try {
      await addShoppingItems(items);
      setAdding(null);
      setToast(
        `${items.length} ingredient${items.length === 1 ? "" : "s"} added to the shopping list`,
      );
      setTimeout(() => setToast(null), 2600);
    } catch (e: unknown) {
      setError(String(e));
      setAdding(null);
    }
  }

  if (error) {
    return (
      <section className="library">
        <p className="error">Could not load recipes: {error}</p>
      </section>
    );
  }

  const inPrompt = matched?.filter((m) => m.inPrompt).length ?? 0;
  const mode = profile.settings.recipeMode ?? "mix";

  return (
    <section className="library recipes">
      <header className="toolbar">
        <div>
          <h1>Inspiration</h1>
          <p className="muted">
            {view === "matches"
              ? matched
                ? mode === "none"
                  ? `${matched.length} aftensretter bruger noget fra køleskabet eller et tilbud — online opskrifter er slået fra i dine planlægningsindstillinger.`
                  : `${matched.length} aftensretter bruger noget fra køleskabet eller et tilbud — de ${inPrompt} bedste sendes med til planlæggeren.`
                : "Finder opskrifter der passer til køleskabet og ugens tilbud…"
              : `${recipes?.length ?? "…"} opskrifter importeret.`}
          </p>
        </div>
        <input
          type="search"
          className="recipe-search"
          placeholder="Søg i titel, kategori eller ingrediens…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShown(PAGE);
          }}
        />
      </header>

      <div className="recipe-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={view === "matches"}
          className={view === "matches" ? "on" : ""}
          onClick={() => switchView("matches")}
        >
          Til ugens madplan
        </button>
        <button
          role="tab"
          aria-selected={view === "all"}
          className={view === "all" ? "on" : ""}
          onClick={() => switchView("all")}
        >
          Alle opskrifter
        </button>
      </div>

      {source === null ? (
        <p className="muted">Loading…</p>
      ) : source.length === 0 ? (
        <div className="empty-state">
          <p className="muted">
            {view === "matches"
              ? "Ingen aftensretter bruger noget fra køleskabet eller ugens tilbud. "
              : ""}
            No recipes imported? Run{" "}
            <code>uv run food-planer-recipes valdemarsro</code>.
          </p>
        </div>
      ) : (
        <>
          {query && (
            <p className="muted recipe-count">
              {filtered.length} match{filtered.length === 1 ? "" : "es"}
            </p>
          )}
          <div className="grid">
            {filtered.slice(0, shown).map((recipe) => (
              <RecipeCard
                key={recipe.url}
                recipe={recipe}
                onDetails={() => setDetails(recipe)}
                onAdd={() => setAdding(recipe)}
              />
            ))}
          </div>
          {shown < filtered.length && (
            <div className="recipe-more">
              <button className="btn" onClick={() => setShown((n) => n + PAGE)}>
                Vis flere ({filtered.length - shown} tilbage)
              </button>
            </div>
          )}
        </>
      )}

      {details && (
        <DetailsModal
          suggestion={recipeAsSuggestion(details)}
          known={null}
          onClose={() => setDetails(null)}
        />
      )}
      {adding && (
        <IngredientReview
          selected={[
            { key: adding.url, dayLabel: "Inspiration", suggestion: recipeAsSuggestion(adding) },
          ]}
          onCancel={() => setAdding(null)}
          onConfirm={(items) => void handleAdd(items)}
        />
      )}
      {toast && <div className="toast">✓ {toast}</div>}
    </section>
  );
}
