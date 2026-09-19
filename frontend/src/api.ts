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

export function deleteDish(id: string): Promise<void> {
  return fetch(`/api/dishes/${id}`, { method: "DELETE" }).then((r) => {
    // The backend answers 204, but any 2xx counts as success (r.ok covers it).
    if (!r.ok) throw new Error(r.statusText);
  });
}
