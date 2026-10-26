import { offerFor } from "./OfferTag";
import type { Discount, Suggestion, SuggestionIngredient } from "./api";

// Long ingredient lists read best in the recipe's own sub-lists, and within
// each, by what it takes to get them: what's in the pantry first, then what's
// in the fridge, then what's on offer, then everything still to buy. The
// recipe's order is kept inside each tier.

export type IngredientRow = {
  ingredient: SuggestionIngredient;
  offer: Discount | undefined;
};

export type IngredientGroup = {
  heading: string | null; // null: the recipe's main list
  rows: IngredientRow[];
};

function tier({ ingredient, offer }: IngredientRow): number {
  if (ingredient.have === "staple") return 0;
  if (ingredient.have === "fresh") return 1;
  return offer ? 2 : 3;
}

export function orderedIngredients(suggestion: Suggestion): IngredientGroup[] {
  const groups = new Map<string | null, IngredientRow[]>();
  for (const ingredient of suggestion.ingredients) {
    const heading = ingredient.group ?? null;
    if (!groups.has(heading)) groups.set(heading, []);
    groups.get(heading)!.push({ ingredient, offer: offerFor(ingredient, suggestion.discounts) });
  }
  // The main list first, then the sub-lists in the order the recipe has them.
  const headings = [...groups.keys()].sort((a, b) => (a === null ? -1 : b === null ? 1 : 0));
  return headings.map((heading) => ({
    heading,
    // Array.prototype.sort is stable, so recipe order survives within a tier.
    rows: [...groups.get(heading)!].sort((a, b) => tier(a) - tier(b)),
  }));
}
