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
};

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

export type SuggestionIngredient = {
  name: string;
  quantity: string; // free text: "200 g", "1 pinch"
};

export type Discount = {
  productName: string;
  shop: string;
  price: number;
  originalPrice: number;
  discountPercent: number;
  validUntil: string;
  matchedIngredient: string | null;
};

export type Suggestion = {
  title: string;
  description: string;
  ingredients: SuggestionIngredient[];
  estimatedCost: number; // DKK
  prepTimeMinutes: number;
  sourceDish: string | null; // a Dish id; null means an invented dish
  discounts: Discount[];
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
