// Typed wrappers over the same-origin /api endpoints.
//
// Profiles (issue #17): the backend is the single source of truth; localStorage
// holds only the profileId pointer.
// Dishes (issue #18): title required; ingredients, substitutes and recipe are
// optional freeform text; PUT is a full replace.

export type PlanningSettings = {
  daysToPlan: number;
  suggestionsPerDay: number;
  knownVsUnknownBias: number;
  priority: string[];
  shops: string[];
  inspiration: string;
  // How the planner uses imported online recipes: every suggestion, about
  // half of them, or none.
  recipeMode: RecipeMode;
};

export type RecipeMode = "only" | "mix" | "none";

export type ProfileSummary = {
  id: string;
  email: string;
  name: string;
};

export type Profile = ProfileSummary & {
  settings: PlanningSettings;
};

export type Dish = {
  id: string;
  title: string;
  ingredients: string | null;
  substitutes: string | null;
  recipe: string | null;
  favourite: boolean;
};

// The writable fields — everything a Dish is except its backend-assigned id.
export type DishInput = Omit<Dish, "id">;

// Planning a week (issue #23): one press → one structured LLM call → a whole
// week, returned synchronously and persisted server-side.

// What we already have of an ingredient: a fresh item in the fridge or a
// pantry staple. Absent/null means it needs buying.
export type OnHand = "fresh" | "staple" | null;

export type SuggestionIngredient = {
  name: string;
  quantity: string; // free text: "200 g", "1 pinch"
  have?: OnHand;
};

// The imported recipe a Suggestion is based on: its link, thumbnail and the
// recipe's own times and servings (prepTimeMinutes is set from totalTime).
export type SuggestionRecipe = {
  title: string;
  url: string;
  source: string | null;
  thumbnail: string | null;
  totalTime: string | null;
  workTime: string | null;
  servings: string | null;
};

// One offer a Suggestion draws on, denormalized in full when the run was made
// so an archived plan still shows it after it expires. `matchedIngredient`
// names the ingredient it covers, as written in the Suggestion's list.
export type Discount = {
  offerId: string;
  productName: string;
  description: string | null;
  shop: string;
  price: number | null;
  originalPrice: number | null;
  discountPercent: number | null;
  unitSize: string | null;
  validFrom: string | null;
  validUntil: string | null;
  imageUrl: string | null;
  matchedIngredient: string | null;
  // Who tied it to the dish: cited by the model, an exact name match, or an
  // uncertain name match the model confirmed in review.
  matchedBy?: "model" | "name" | "review";
};

export type Suggestion = {
  title: string;
  description: string;
  ingredients: SuggestionIngredient[];
  estimatedCost: number; // DKK
  prepTimeMinutes: number;
  sourceDish: string | null; // a Dish id; null means an invented dish
  discounts: Discount[];
  recipe?: SuggestionRecipe | null;
};

export type DayPlan = {
  day: number;
  suggestions: Suggestion[];
};

export type PlanningRun = {
  id: string;
  createdAt: string;
  profileId: string;
  profileName: string;
  status: "success" | "partial" | "failed";
  days: DayPlan[];
  dayCount: number;
  dishIds: string[];
  fridgeSnippet: string;
  requestedDays: number | null;
  requestedSuggestionsPerDay: number | null;
  // How many offers the model was shown, and preferred chains whose
  // tilbudsavis couldn't be fetched (absent on runs made before offers).
  offerCount?: number;
  offersUnavailable?: string[];
  // Why the model call failed (a timeout, an API outage), on a failed run.
  error?: string | null;
};

// A row of the Past-plans archive (issue #26). The list endpoint ships these
// summaries — never every suggestion of every week just to draw the list; the
// full run (with days/suggestions) is fetched on demand by id.
export type PlanningRunSummary = {
  id: string;
  createdAt: string;
  profileId: string;
  profileName: string;
  dayCount: number;
  status: "success" | "partial" | "failed";
  fridgeSnippet: string;
};

export type SettingsOverride = {
  daysToPlan: number;
  suggestionsPerDay: number;
  knownVsUnknownBias: number;
};

// A row of the backend-owned Danish-chain catalog (issue #20). `hasIcon` lets a
// pill choose the coloured-initial fallback without a failed image request.
export type Shop = {
  slug: string;
  name: string;
  hasIcon: boolean;
};

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const detail = await resp
      .json()
      .then((b: { detail?: string }) => b.detail)
      .catch(() => resp.statusText);
    throw new Error(detail ?? resp.statusText);
  }
  return resp.json() as Promise<T>;
}

// Find-or-create: a new email creates a Profile; an existing one wins and the
// typed name is discarded server-side.
export async function identify(email: string, name: string): Promise<Profile> {
  const resp = await fetch("/api/profiles/identify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, name }),
  });
  return json<Profile>(resp);
}

export async function listProfiles(): Promise<ProfileSummary[]> {
  return json<ProfileSummary[]>(await fetch("/api/profiles"));
}

// Resolve the stored pointer. Returns null when the id no longer exists (e.g.
// a wiped data/), so the caller falls back to the identify screen.
export async function getProfile(id: string): Promise<Profile | null> {
  const resp = await fetch(`/api/profiles/${id}`);
  if (resp.status === 404) return null;
  return json<Profile>(resp);
}

// Save a Profile's PlanningSettings alone (issue #19). The Settings screen
// never round-trips name and email just to save a slider, so this PUTs the
// settings block by itself and gets the updated Profile back.
export function saveSettings(
  id: string,
  settings: PlanningSettings,
): Promise<Profile> {
  return fetch(`/api/profiles/${id}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }).then((r) => json<Profile>(r));
}

// The fixed Danish-chain catalog for the preferred-shops picker (issue #20).
export function listShops(): Promise<Shop[]> {
  return fetch("/api/shops").then((r) => json<Shop[]>(r));
}

// The URL a pill's logo loads from — only issued when the shop hasIcon.
export function shopIconUrl(slug: string): string {
  return `/api/shops/${encodeURIComponent(slug)}/icon`;
}

export function listDishes(): Promise<Dish[]> {
  return fetch("/api/dishes").then((r) => json<Dish[]>(r));
}

// Recipes imported from recipe websites by `food-planer-recipes <site>`.
// Read-only; each one links out to its source page for the full method.
export type RecipeIngredient = {
  text: string; // the line as the recipe writes it
  group: string | null; // the sub-heading it sits under, e.g. "Til servering"
  name: string; // the shopping item: "500 g porre, i ringe" → "porre"
  quantity: string; // … and "500 g"
  have?: OnHand;
};

// An imported recipe shaped like a Suggestion card: what it'd cost roughly,
// how many of its ingredients are in the fridge, the pantry or on offer, and
// the offers themselves (as a Suggestion's discounts).
export type Recipe = {
  source: string;
  url: string;
  title: string;
  thumbnail: string | null;
  servings: string | null;
  total_time: string | null;
  categories: string[];
  description: string;
  ingredients: RecipeIngredient[];
  discounts: (Discount & { review?: boolean })[];
  estimatedCost: number; // rough, DKK
  prepTimeMinutes: number | null;
  counts: { fresh: number; staple: number; offers: number };
  recipe: SuggestionRecipe;
};

// With a profile, the cards include this week's offers at its shops.
export function listRecipes(profileId?: string): Promise<Recipe[]> {
  const query = profileId ? `?profileId=${encodeURIComponent(profileId)}` : "";
  return fetch(`/api/recipes${query}`).then((r) => json<Recipe[]>(r));
}

// A recipe card as a Suggestion, so the plan's Details and Add-ingredients
// modals work on it unchanged.
export function recipeAsSuggestion(recipe: Recipe): Suggestion {
  return {
    title: recipe.title,
    description: recipe.description,
    ingredients: recipe.ingredients.map(({ name, quantity, have }) => ({ name, quantity, have })),
    estimatedCost: recipe.estimatedCost,
    prepTimeMinutes: recipe.prepTimeMinutes ?? 0,
    sourceDish: null,
    discounts: recipe.discounts,
    recipe: recipe.recipe,
  };
}

// A dinner recipe the planner would consider this week, and why: the fresh
// items it uses up and the offers it uses, ranked the way the planner ranks
// them. `inPrompt` marks the ones the planner actually sees.
export type RecipeMatch = Recipe & {
  score: number;
  inPrompt: boolean;
  fresh: { item: string; ingredient: string }[];
  offers: {
    ingredient: string;
    shop: string;
    productName: string;
    price: number | null;
    review: boolean; // not a 1:1 match: the planner is asked to check it
  }[];
};

export function listRecipeMatches(profileId: string): Promise<RecipeMatch[]> {
  return fetch(`/api/recipes/matches?profileId=${encodeURIComponent(profileId)}`).then(
    (r) => json<RecipeMatch[]>(r),
  );
}

export function createDish(input: DishInput): Promise<Dish> {
  return fetch("/api/dishes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((r) => json<Dish>(r));
}

// Full replace: the stored Dish becomes exactly `input`, so any field left
// empty here (e.g. recipe: null) is cleared, not preserved.
export function replaceDish(id: string, input: DishInput): Promise<Dish> {
  return fetch(`/api/dishes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((r) => json<Dish>(r));
}

// One press of "Plan my week" — the finished run comes back synchronously, so
// there is nothing to poll. A failed run still returns 200 with its body.
export function planWeek(
  profileId: string,
  settingsOverride?: SettingsOverride,
): Promise<PlanningRun> {
  return fetch("/api/planning-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profileId, settingsOverride }),
  }).then((r) => json<PlanningRun>(r));
}

// The Past-plans archive (issue #26): every run the household has ever made,
// newest first and household-wide (not just the current Profile's), as
// summaries. Picking one loads its full run via getPlanningRun.
export function listPlanningRuns(): Promise<PlanningRunSummary[]> {
  return fetch("/api/planning-runs").then((r) =>
    json<PlanningRunSummary[]>(r),
  );
}

// One full run by id — the days and suggestions the summary deliberately omits.
export function getPlanningRun(id: string): Promise<PlanningRun> {
  return fetch(`/api/planning-runs/${encodeURIComponent(id)}`).then((r) =>
    json<PlanningRun>(r),
  );
}

// One ingredient headed for the household ShoppingList (issue #29). `source`
// carries the dish it came from (null for a hand-added item); the backend
// generates the line id and merges rows on read, so nothing is returned here
// that the Plan-a-week screen needs — selection is pure frontend state.
export type ShoppingItemInput = {
  name: string;
  quantity: string;
  source: { suggestionTitle: string; kind: "known" | "unknown" } | null;
  // A free-text note carried by a hand-added item; surfaces in the CSV Notes
  // column for rows that have no dish behind them.
  note?: string;
};

// A merged ShoppingList row as the backend folds it (issue #22/#29): one row
// per ingredient, the total summed across every dish, each dish's share on its
// source entry. `dishTitle`/`kind` are null for a hand-added contribution.
export type ShoppingRow = {
  name: string;
  totalQuantity: string;
  sources: {
    dishTitle: string | null;
    kind: "known" | "unknown" | null;
    share: string;
  }[];
  lineIds: string[];
  note: string;
};

export function getShoppingList(): Promise<ShoppingRow[]> {
  return fetch("/api/shopping-list").then((r) => json<ShoppingRow[]>(r));
}

// Remove rows from the list (every line behind each merged row); returns the
// list as it now stands. Clearing everything is the same call with every id.
export function removeShoppingRows(rows: ShoppingRow[]): Promise<ShoppingRow[]> {
  return fetch("/api/shopping-list/items/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lineIds: rows.flatMap((r) => r.lineIds) }),
  }).then((r) => json<ShoppingRow[]>(r));
}

// The plain-text export the Copy-list modal previews. The backend owns the
// formatting (totals, per-dish shares in brackets) so it stays consistent with
// the CSV and is unit-tested behind the seam.
export function getShoppingListText(): Promise<string> {
  return fetch("/api/shopping-list/export.txt").then((r) => {
    if (!r.ok) throw new Error(r.statusText);
    return r.text();
  });
}

// The CSV download URL. Served with a UTF-8 BOM and a Content-Disposition so a
// plain anchor download writes shopping-list.csv and Excel reads æ/ø/å back.
export const SHOPPING_LIST_CSV_URL = "/api/shopping-list/export.csv";

// Post the reviewed ingredients as one array — a whole selection's worth of
// ingredients is a single request, cleared client-side once it succeeds.
export function addShoppingItems(items: ShoppingItemInput[]): Promise<void> {
  return fetch("/api/shopping-list/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  }).then((r) => {
    if (!r.ok) throw new Error(r.statusText);
  });
}

export function deleteDish(id: string): Promise<void> {
  return fetch(`/api/dishes/${id}`, { method: "DELETE" }).then((r) => {
    // The backend answers 204, but any 2xx counts as success (r.ok covers it).
    if (!r.ok) throw new Error(r.statusText);
  });
}

// The planning prompt: one household-wide template. Values derived from the
// library and a Profile's settings are injected wherever a {{variable}}
// appears; the backend refuses a template naming a variable it can't fill.
export type PromptVariable = { name: string; description: string };

export type PromptConfig = {
  template: string;
  isDefault: boolean;
  defaultTemplate: string;
  // How many tilbudsavis offers the prompt lists (0 = none).
  offerLimit: number;
  defaultOfferLimit: number;
  offerLimitCeiling: number;
  variables: PromptVariable[];
};

// One piece of a rendered prompt: the template's own text (variable null) or
// the value injected for a {{variable}}.
export type PromptSegment = { text: string; variable: string | null };

export function getPrompt(): Promise<PromptConfig> {
  return fetch("/api/prompt").then((r) => json<PromptConfig>(r));
}

// A full replace: `null` for either resets it to the built-in default.
export function savePrompt(
  template: string | null,
  offerLimit: number | null,
): Promise<PromptConfig> {
  return fetch("/api/prompt", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template, offerLimit }),
  }).then((r) => json<PromptConfig>(r));
}

// Render a draft template for a Profile without saving it or calling the model.
export function previewPrompt(
  profileId: string,
  template: string,
  offerLimit: number,
): Promise<PromptSegment[]> {
  return fetch("/api/prompt/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profileId, template, offerLimit }),
  })
    .then((r) => json<{ segments: PromptSegment[] }>(r))
    .then((b) => b.segments);
}

// One product on offer in a chain's tilbudsavis, in the spec's Offer shape.
// `pre_price` is only set when a markdown is advertised, and so is
// `discount_percent`; most offers are a flat weekly price.
export type Offer = {
  id: string;
  source: "tjek_api";
  item_name: string;
  description: string | null;
  shop: string;
  price: number | null;
  pre_price: number | null;
  discount_percent: number | null;
  currency: string;
  unit_size: string | null;
  valid_from: string | null;
  valid_to: string | null;
  image_url: string | null;
  fetched_at: string;
};

// `dealer` is null for a chain the tilbudsavis doesn't carry.
export type ShopOffers = {
  shop: { slug: string; name: string };
  dealer: { id: string; name: string } | null;
  offers: Offer[];
  fetchedAt: string | null;
};

export function getShopOffers(slug: string): Promise<ShopOffers> {
  return fetch(`/api/shops/${encodeURIComponent(slug)}/offers`).then((r) =>
    json<ShopOffers>(r),
  );
}

// What is in the fridge: household-shared. Fresh items keep for less than
// about a month and come and go by hand or by a photo scan; pantry staples
// keep longer and are assumed always in the house. `common` lists, per kind,
// the basic items plus every name added before, minus what's already in.
export type FridgeKind = "fresh" | "staple";

export type FridgeItem = {
  id: string;
  name: string;
  kind: FridgeKind;
  addedAt: string;
};

export type Fridge = {
  fresh: FridgeItem[];
  staples: FridgeItem[];
  common: Record<FridgeKind, string[]>;
};

export type ScannedItem = { name: string; kind: FridgeKind };

export function getFridge(): Promise<Fridge> {
  return fetch("/api/fridge").then((r) => json<Fridge>(r));
}

export function addFridgeItems(items: ScannedItem[]): Promise<Fridge> {
  return fetch("/api/fridge/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  }).then((r) => json<Fridge>(r));
}

// Empty one kind: every fresh item, or every pantry staple.
export function clearFridge(kind: FridgeKind): Promise<Fridge> {
  return fetch(`/api/fridge/items?kind=${kind}`, { method: "DELETE" }).then((r) =>
    json<Fridge>(r),
  );
}

export function removeFridgeItem(id: string): Promise<Fridge> {
  return fetch(`/api/fridge/items/${encodeURIComponent(id)}`, {
    method: "DELETE",
  }).then((r) => json<Fridge>(r));
}

// Send photos to be read by the model. Nothing is saved: the caller reviews
// the returned list and adds what's right with addFridgeItems.
export function scanFridge(images: Blob[]): Promise<ScannedItem[]> {
  const form = new FormData();
  images.forEach((img, i) => form.append("images", img, `photo-${i + 1}.jpg`));
  return fetch("/api/fridge/scan", { method: "POST", body: form })
    .then((r) => json<{ items: ScannedItem[] }>(r))
    .then((b) => b.items);
}
