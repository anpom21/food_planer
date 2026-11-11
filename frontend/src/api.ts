// Typed wrappers over the same-origin /api endpoints.
//
// Settings: one household-wide set of planning preferences (no profiles).
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
  // A recipe dish's sub-list ("Til servering"); null for the main list.
  group?: string | null;
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
  // The settings slug of the offer's shop ("coop-365"); null for a dealer
  // that isn't one of the known chains. Dishes only show offers from shops
  // that are selected in settings.
  shopSlug?: string | null;
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
  dayCount: number;
  status: "success" | "partial" | "failed";
  fridgeSnippet: string;
};

// The settings for a single run, from the Suggest dishes sheet: on top of the
// saved ones, never written back. Anything left out keeps its saved value.
export type SettingsOverride = Partial<PlanningSettings>;

// A row of the backend-owned Danish-chain catalog (issue #20). `hasIcon` lets a
// pill choose the coloured-initial fallback without a failed image request.
export type Shop = {
  slug: string;
  name: string;
  hasIcon: boolean;
};

// Fired when the server says the session is gone (signed out elsewhere, or a
// password change on another device), so the app can show the sign-in screen.
export const SIGNED_OUT_EVENT = "food-planner:signed-out";

async function json<T>(resp: Response): Promise<T> {
  if (resp.status === 401 && !resp.url.includes("/api/auth/")) {
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
  if (!resp.ok) {
    const detail = await resp
      .json()
      .then((b: { detail?: string }) => b.detail)
      .catch(() => resp.statusText);
    throw new Error(detail ?? resp.statusText);
  }
  return resp.json() as Promise<T>;
}

// Accounts: someone signing up alone starts a household of their own; an
// invite link joins its household instead. A password is optional; the server
// keeps only a one-way hash of it.
export type Me = {
  id: string;
  username: string;
  hasPassword: boolean;
  owner: boolean; // the server's first user, who may use its own model keys
  householdId: string;
};

function postJson<T>(url: string, body: unknown): Promise<T> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<T>(r));
}

// null when nobody is signed in on this device.
export async function getMe(): Promise<Me | null> {
  const resp = await fetch("/api/auth/me");
  if (resp.status === 401) return null;
  return json<Me>(resp);
}

// With an invite token, the new user joins the inviter's household.
export function signUp(
  username: string,
  password: string | null,
  invite?: string | null,
): Promise<Me> {
  return postJson<Me>("/api/auth/signup", { username, password, invite: invite ?? null });
}

export function signIn(username: string, password: string | null): Promise<Me> {
  return postJson<Me>("/api/auth/login", { username, password });
}

export async function signOut(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
}

// newPassword null removes the password.
export function changePassword(
  currentPassword: string | null,
  newPassword: string | null,
): Promise<Me> {
  return fetch("/api/auth/password", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ currentPassword, newPassword }),
  }).then((r) => json<Me>(r));
}

// --- The household: members, invite links, appearance ------------------------

// What an invite link says before anyone signs up through it. Rejects with
// "This invite link has expired…" once it's no good.
export type InvitePreview = {
  householdName: string;
  invitedBy: string;
  expiresAt: string;
};

export function checkInvite(token: string): Promise<InvitePreview> {
  return fetch(`/api/invites/${encodeURIComponent(token)}`).then((r) =>
    json<InvitePreview>(r),
  );
}

export type Invite = {
  id: string;
  createdBy: string;
  createdAt: string;
  expiresAt: string;
};

export type HouseholdInfo = {
  id: string;
  name: string;
  members: { id: string; username: string }[];
  invites: Invite[];
};

export function getHouseholdInfo(): Promise<HouseholdInfo> {
  return fetch("/api/household").then((r) => json<HouseholdInfo>(r));
}

// A new invite link's token comes back this once; the server keeps a digest.
export function createInvite(): Promise<Invite & { token: string }> {
  return postJson<Invite & { token: string }>("/api/household/invites", {});
}

export async function revokeInvite(id: string): Promise<void> {
  const resp = await fetch(`/api/household/invites/${id}`, { method: "DELETE" });
  if (!resp.ok) await json(resp);
}

// Moves the signed-in user into the invite's household.
export function joinHousehold(invite: string): Promise<Me> {
  return postJson<Me>("/api/household/join", { invite });
}

// The link someone opens to join: the app's own address with the token.
export function inviteUrl(token: string): string {
  return `${window.location.origin}/?invite=${encodeURIComponent(token)}`;
}

// How the household has personalised the app; null is the app's own look.
export type Appearance = {
  name: string | null;
  emoji: string | null;
  accent: string | null;
};

export function getAppearance(): Promise<Appearance> {
  return fetch("/api/household/appearance").then((r) => json<Appearance>(r));
}

export function saveAppearance(appearance: Appearance): Promise<Appearance> {
  return fetch("/api/household/appearance", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(appearance),
  }).then((r) => json<Appearance>(r));
}

export function getSettings(): Promise<PlanningSettings> {
  return fetch("/api/settings").then((r) => json<PlanningSettings>(r));
}

// A full replace: the household's settings become exactly `settings`.
export function saveSettings(settings: PlanningSettings): Promise<PlanningSettings> {
  return fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }).then((r) => json<PlanningSettings>(r));
}

// Settings → Model: which LLM plans, scans and reviews. Secrets are write-only:
// the backend says whether one is set, never what it is.
export type ModelProvider = "openai" | "claude-code";

export type ModelSettings = {
  provider: ModelProvider;
  openaiModel: string | null;
  claudeModel: string | null;
  openaiKeySet: boolean;
  openaiKeyHint: string | null;
  openaiKeyFromEnv: boolean;
  defaultOpenaiModel: string;
  defaultClaudeModel: string;
  claudeTokenSet: boolean;
  // Not the server's owner: a key or token of their own is needed.
  usesOwnCredentialsOnly: boolean;
};

export type ModelSettingsUpdate = {
  provider: ModelProvider;
  openaiModel: string | null;
  claudeModel: string | null;
  // undefined/null keeps the stored secret, "" removes it.
  openaiApiKey?: string | null;
  claudeToken?: string | null;
};

export type ClaudeStatus = {
  installed: boolean;
  loggedIn: boolean;
  authMethod?: string | null;
  email?: string | null;
  subscriptionType?: string | null;
  error?: string;
  // Not the server's owner and no token saved: they need their own.
  needsToken?: boolean;
};

export function getModelSettings(): Promise<ModelSettings> {
  return fetch("/api/model").then((r) => json<ModelSettings>(r));
}

export function saveModelSettings(update: ModelSettingsUpdate): Promise<ModelSettings> {
  return fetch("/api/model", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  }).then((r) => json<ModelSettings>(r));
}

export function getClaudeStatus(): Promise<ClaudeStatus> {
  return fetch("/api/model/claude-status").then((r) => json<ClaudeStatus>(r));
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
  discounts: Discount[]; // 1:1 offer matches only
  estimatedCost: number; // rough, DKK
  prepTimeMinutes: number | null;
  counts: { fresh: number; staple: number; offers: number };
  recipe: SuggestionRecipe;
};

// Every imported recipe, with this week's offers at the household's shops.
export function listRecipes(): Promise<Recipe[]> {
  return fetch("/api/recipes").then((r) => json<Recipe[]>(r));
}

// A recipe card as a Suggestion, so the plan's Details and Add-ingredients
// modals work on it unchanged.
export function recipeAsSuggestion(recipe: Recipe): Suggestion {
  return {
    title: recipe.title,
    description: recipe.description,
    ingredients: recipe.ingredients.map(({ name, quantity, have, group }) => ({
      name,
      quantity,
      have,
      group,
    })),
    estimatedCost: recipe.estimatedCost,
    prepTimeMinutes: recipe.prepTimeMinutes ?? 0,
    sourceDish: null,
    discounts: recipe.discounts,
    recipe: recipe.recipe,
  };
}

// A library Dish shaped as a Suggestion, so it opens, adds ingredients and
// goes into My week like a planned dish. Its ingredients are free text, one
// per line, so each line is the name and there's no separate quantity.
export function dishAsSuggestion(dish: Dish): Suggestion {
  return {
    title: dish.title,
    description: dish.recipe ?? "",
    ingredients: (dish.ingredients ?? "")
      .split("\n")
      .map((line) => line.replace(/^[-•*]\s*/, "").trim())
      .filter(Boolean)
      .map((name) => ({ name, quantity: "" })),
    estimatedCost: 0,
    prepTimeMinutes: 0,
    sourceDish: dish.id,
    discounts: [],
    recipe: null,
  };
}

// My week: the dishes chosen for each week. A week is named by its Monday
// ("2026-10-26"); entries from earlier weeks stay to look back through.
export type MyWeekEntry = {
  id: string;
  week: string;
  addedAt: string;
  suggestion: Suggestion;
};

export type MyWeek = {
  currentWeek: string;
  entries: MyWeekEntry[]; // every week, oldest first
};

export function getMyWeek(): Promise<MyWeek> {
  return fetch("/api/my-week").then((r) => json<MyWeek>(r));
}

// Adding a title the week already has returns that entry with created: false.
export function addToMyWeek(
  suggestion: Suggestion,
  week?: string,
): Promise<{ entry: MyWeekEntry; created: boolean }> {
  return fetch("/api/my-week", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ suggestion, week }),
  }).then((r) => json<{ entry: MyWeekEntry; created: boolean }>(r));
}

export async function removeFromMyWeek(id: string): Promise<void> {
  const resp = await fetch(`/api/my-week/${id}`, { method: "DELETE" });
  if (!resp.ok) await json(resp);
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

export function listRecipeMatches(): Promise<RecipeMatch[]> {
  return fetch("/api/recipes/matches").then((r) => json<RecipeMatch[]>(r));
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
export function planWeek(settingsOverride?: SettingsOverride): Promise<PlanningRun> {
  return fetch("/api/planning-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settingsOverride }),
  }).then((r) => json<PlanningRun>(r));
}

// The Past-plans archive (issue #26): every run the household has ever made,
// newest first, as summaries. Picking one loads its full run via getPlanningRun.
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
  // The offer the ingredient was on, so the list keeps its shop.
  offer?: ShoppingOffer | null;
};

export type ShoppingOffer = {
  shop: string; // as Tjek names it, e.g. "365discount"
  shopSlug: string | null; // the settings slug, e.g. "coop-365"
  productName: string;
  price: number | null;
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
  // The offers behind the row; rows arrive grouped by the first one's shop.
  offers: ShoppingOffer[];
};

export function getShoppingList(): Promise<ShoppingRow[]> {
  return fetch("/api/shopping-list").then((r) => json<ShoppingRow[]>(r));
}

// The list as reminders for the iPhone's Påmindelser: a title and a subtext
// (amount · which dishes) per row. Only `rows` when given, else everything.
export type Reminder = { title: string; notes: string };

export function exportReminders(rows?: ShoppingRow[]): Promise<Reminder[]> {
  return fetch("/api/shopping-list/export/reminders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rows ? { lineIds: rows.flatMap((r) => r.lineIds) } : {}),
  })
    .then((r) => json<{ items: Reminder[] }>(r))
    .then((b) => b.items);
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
// library and the household's settings are injected wherever a {{variable}}
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

// Render a draft template without saving it or calling the model.
export function previewPrompt(template: string, offerLimit: number): Promise<PromptSegment[]> {
  return fetch("/api/prompt/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template, offerLimit }),
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
