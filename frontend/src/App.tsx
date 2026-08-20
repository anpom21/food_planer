import { useEffect, useState } from "react";
import type { Dish, DishInput } from "./api";
import {
  createDish,
  deleteDish,
  listDishes,
  replaceDish,
} from "./api";
import { DishEditor } from "./DishEditor";
import "./app.css";

// The Dish library screen (issue #18): a three-column card grid the household
// shares. Adding a dish takes a title and five seconds; everything else is
// optional detail behind one toggle in the editor.

// A card's excerpt is whichever optional field is filled first, in the order
// recipe → ingredients → substitutes. When the card carries no ⭐ label the
// freed row lets the excerpt run longer.
const EXCERPT_UNTAGGED = 130;
const EXCERPT_TAGGED = 70;

function excerptFor(dish: Dish): string {
  const source = dish.recipe || dish.ingredients || dish.substitutes || "";
  const limit = dish.favourite ? EXCERPT_TAGGED : EXCERPT_UNTAGGED;
  if (source.length <= limit) return source;
  return source.slice(0, limit) + "…";
}

// `null` = editor closed; a Dish = editing it; "new" = the add flow.
type EditorTarget = Dish | "new" | null;

export function App() {
  const [dishes, setDishes] = useState<Dish[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditorTarget>(null);

  useEffect(() => {
    listDishes().then(setDishes).catch((e: unknown) => setError(String(e)));
  }, []);

  async function handleSave(input: DishInput) {
    const saved =
      editing && editing !== "new"
        ? await replaceDish(editing.id, input)
        : await createDish(input);
    setDishes((prev) => {
      const rest = (prev ?? []).filter((d) => d.id !== saved.id);
      return [...rest, saved];
    });
    setEditing(null);
  }

  async function handleDelete(dish: Dish) {
    // A trash icon, distinct from the click-to-edit card, deletes only after
    // an explicit confirm so a mis-click can't lose a Dish.
    if (!window.confirm(`Delete "${dish.title}"?`)) return;
    await deleteDish(dish.id);
    setDishes((prev) => (prev ?? []).filter((d) => d.id !== dish.id));
  }

  if (error) {
    return (
      <main className="library">
        <p className="error">Could not load the Dish library: {error}</p>
      </main>
    );
  }

  if (dishes === null) {
    return (
      <main className="library">
        <p className="muted">Loading…</p>
      </main>
    );
  }

  return (
    <main className="library">
      <header className="toolbar">
        <div>
          <h1>Dish library</h1>
          <p className="muted">The meals your household already knows how to make.</p>
        </div>
        <button className="btn primary" onClick={() => setEditing("new")}>
          + Add Dish
        </button>
      </header>

      {dishes.length === 0 ? (
        <div className="empty-state">
          <button className="btn primary large" onClick={() => setEditing("new")}>
            + Add your first dish
          </button>
        </div>
      ) : (
        <div className="grid">
          {dishes.map((dish) => (
            <article
              key={dish.id}
              className="card"
              role="button"
              tabIndex={0}
              onClick={() => setEditing(dish)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setEditing(dish);
                }
              }}
            >
              <button
                className="card-delete"
                title="Delete"
                aria-label={`Delete ${dish.title}`}
                onClick={(e) => {
                  e.stopPropagation();
                  void handleDelete(dish);
                }}
              >
                🗑
              </button>
              <h2 className="card-title">{dish.title}</h2>
              {dish.favourite && <span className="fav-label">⭐ Favourite</span>}
              <p className="card-excerpt">
                {excerptFor(dish) || (
                  <em className="muted">No extra detail added yet</em>
                )}
              </p>
            </article>
          ))}

          {/* The dashed end-of-grid tile — a third way into the same add flow. */}
          <button
            className="card add-tile"
            onClick={() => setEditing("new")}
          >
            + Add Dish
          </button>
        </div>
      )}

      {editing !== null && (
        <DishEditor
          dish={editing === "new" ? null : editing}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}
    </main>
  );
}
