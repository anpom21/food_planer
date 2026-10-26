import type { SuggestionRecipe } from "./api";
import "./recipelink.css";

// The link from a Suggestion back to the imported recipe it's based on. The
// thumbnail and the button both open the recipe on its own site. Clicks stop
// here so they don't also toggle the card's selection.

const stop = (e: React.MouseEvent) => e.stopPropagation();

export function RecipeThumb({ recipe }: { recipe: SuggestionRecipe }) {
  if (!recipe.thumbnail) return null;
  return (
    <a
      className="recipe-link-thumb"
      href={recipe.url}
      target="_blank"
      rel="noreferrer"
      onClick={stop}
      aria-label={`${recipe.title} (opens the recipe)`}
      title="Open the recipe"
    >
      <img src={recipe.thumbnail} alt="" loading="lazy" />
      <span className="recipe-link-hint">Open recipe ↗</span>
    </a>
  );
}

export function RecipeButton({ recipe }: { recipe: SuggestionRecipe }) {
  return (
    <a
      className="btn primary recipe-link-btn"
      href={recipe.url}
      target="_blank"
      rel="noreferrer"
      onClick={stop}
    >
      Gå til opskrift
    </a>
  );
}

// The recipe's own facts, as the site states them: "Tid i alt 1 time 10 min ·
// Arbejdstid 20 min · 4 pers. · valdemarsro".
export function RecipeFacts({ recipe }: { recipe: SuggestionRecipe }) {
  const facts = [
    recipe.totalTime && `Tid i alt ${recipe.totalTime}`,
    recipe.workTime && recipe.workTime !== recipe.totalTime && `Arbejdstid ${recipe.workTime}`,
    recipe.servings,
    recipe.source,
  ].filter(Boolean);
  return <p className="recipe-link-facts">{facts.join(" · ")}</p>;
}
