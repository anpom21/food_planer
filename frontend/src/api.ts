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

export type SettingsOverride = {
  daysToPlan: number;
  suggestionsPerDay: number;
  knownVsUnknownBias: number;
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

export function deleteDish(id: string): Promise<void> {
  return fetch(`/api/dishes/${id}`, { method: "DELETE" }).then((r) => {
    // The backend answers 204, but any 2xx counts as success (r.ok covers it).
    if (!r.ok) throw new Error(r.statusText);
  });
}
