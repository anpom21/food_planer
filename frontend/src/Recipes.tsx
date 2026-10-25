import { useEffect, useMemo, useState } from "react";
import {
  listRecipeMatches,
  listRecipes,
  type Recipe,
  type RecipeIngredient,
  type RecipeMatch,
} from "./api";
import { OnHandBadge } from "./OnHand";
import "./recipes.css";

// The Recipes screen: everything imported from recipe websites, as a card grid.
// Each card's thumbnail links to the source page, as does its "Gå til opskrift"
// button; the ingredient list folds out in place. A search matches title,
// category or any ingredient. There are ~1800 recipes, so the grid renders a
// page at a time behind a "Vis flere" button rather than all at once.
//
// The "Til ugens madplan" view shows what the planner works from instead: only
// the dinner recipes that use a fresh item from the Fridge or one of this
// week's offers, ranked the way the planner ranks them, with the top ones
// marked as sent in the prompt.

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

// Consecutive ingredients sharing a sub-heading, in page order.
function grouped(ingredients: RecipeIngredient[]) {
  const groups: { heading: string | null; lines: RecipeIngredient[] }[] = [];
  for (const ingredient of ingredients) {
    const last = groups[groups.length - 1];
    if (last && last.heading === ingredient.group) last.lines.push(ingredient);
    else groups.push({ heading: ingredient.group, lines: [ingredient] });
  }
  return groups;
}

const kr = (price: number) => `${price.toFixed(2).replace(/\.?0+$/, "")} kr`;

function MatchChips({ match }: { match: RecipeMatch }) {
  return (
    <div className="recipe-chips">
      {match.inPrompt && <span className="chip prompt">I prompten</span>}
      {match.fresh.map((f) => (
        <span key={f.item} className="chip fresh" title={`Bruger ${f.ingredient}`}>
          🥬 {f.item}
        </span>
      ))}
      {match.offers.map((o) => (
        <span
          key={`${o.shop}-${o.productName}`}
          className={`chip offer${o.review ? " review" : ""}`}
          title={
            `${o.productName}${o.price != null ? ` — ${kr(o.price)}` : ""}` +
            (o.review ? "\nUsikkert match — planlæggeren tjekker om varen passer" : "")
          }
        >
          🏷 {o.ingredient} · {o.shop}
          {o.review && " ?"}
        </span>
      ))}
    </div>
  );
}

function RecipeCard({ recipe, match }: { recipe: Recipe; match?: RecipeMatch }) {
  const meta = [recipe.total_time, recipe.servings].filter(Boolean).join(" · ");
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
        {meta && <p className="recipe-meta muted">{meta}</p>}
        {match && <MatchChips match={match} />}
        <details className="recipe-ingredients">
          <summary>Ingredienser ({recipe.ingredients.length})</summary>
          {grouped(recipe.ingredients).map((g, i) => (
            <div key={i}>
              {g.heading && <h3>{g.heading}</h3>}
              <ul>
                {g.lines.map((line, j) => (
                  <li key={j}>
                    {line.text}
                    <OnHandBadge have={line.have} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
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

export function Recipes({ profileId }: { profileId: string }) {
  const [view, setView] = useState<View>("matches");
  const [recipes, setRecipes] = useState<Recipe[] | null>(null);
  const [matched, setMatched] = useState<RecipeMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);

  useEffect(() => {
    listRecipes().then(setRecipes).catch((e: unknown) => setError(String(e)));
  }, []);

  // Fetched on first visit to the view: it pulls this week's offers.
  useEffect(() => {
    if (view !== "matches" || matched !== null) return;
    listRecipeMatches(profileId)
      .then(setMatched)
      .catch((e: unknown) => setError(String(e)));
  }, [view, matched, profileId]);

  const source: Recipe[] | null = view === "matches" ? matched : recipes;
  const filtered = useMemo(
    () => (source ?? []).filter((r) => matches(r, query.trim())),
    [source, query],
  );

  const switchView = (next: View) => {
    setView(next);
    setShown(PAGE);
  };

  if (error) {
    return (
      <section className="library">
        <p className="error">Could not load recipes: {error}</p>
      </section>
    );
  }

  if (recipes !== null && recipes.length === 0) {
    return (
      <section className="library">
        <div className="empty-state">
          <p className="muted">
            No recipes yet. Import them with{" "}
            <code>uv run food-planer-recipes valdemarsro</code>.
          </p>
        </div>
      </section>
    );
  }

  const inPrompt = matched?.filter((m) => m.inPrompt).length ?? 0;

  return (
    <section className="library recipes">
      <header className="toolbar">
        <div>
          <h1>Opskrifter</h1>
          <p className="muted">
            {view === "matches"
              ? matched
                ? `${matched.length} aftensretter bruger noget fra køleskabet eller et tilbud — de ${inPrompt} bedste sendes med til planlæggeren.`
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
                match={view === "matches" ? (recipe as RecipeMatch) : undefined}
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
    </section>
  );
}
