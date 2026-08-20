// Thin typed wrapper over the same-origin /api Dish endpoints (issue #18).
// The backend Dish shape: title required; ingredients, substitutes and recipe
// are optional freeform text; PUT is a full replace.

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
