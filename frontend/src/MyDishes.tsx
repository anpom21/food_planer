import { useState } from "react";
import { createDish, deleteDish, replaceDish, type Dish, type DishInput } from "./api";
import { DishEditor } from "./DishEditor";

// The household's own Dish library (issue #18), as one view of the Dishes tab.
// Adding a dish takes a title and five seconds; everything else is optional
// detail behind one toggle in the editor. The list itself lives on the Dishes
// tab, which also saves online recipes into it.

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

export function dishMatches(dish: Dish, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = [dish.title, dish.ingredients, dish.substitutes, dish.recipe]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();
  return q.split(/\s+/).every((word) => haystack.includes(word));
}

// `null` = editor closed; a Dish = editing it; "new" = the add flow.
type EditorTarget = Dish | "new" | null;

export function MyDishes({
  dishes,
  query,
  onChange,
}: {
  dishes: Dish[];
  query: string;
  onChange: (dishes: Dish[]) => void;
}) {
  const [editing, setEditing] = useState<EditorTarget>(null);

  async function handleSave(input: DishInput) {
    const saved =
      editing && editing !== "new"
        ? await replaceDish(editing.id, input)
        : await createDish(input);
    onChange([...dishes.filter((d) => d.id !== saved.id), saved]);
    setEditing(null);
  }

  async function handleDelete(dish: Dish) {
    // A trash icon, distinct from the click-to-edit card, deletes only after
    // an explicit confirm so a mis-click can't lose a Dish.
    if (!window.confirm(`Delete "${dish.title}"?`)) return;
    await deleteDish(dish.id);
    onChange(dishes.filter((d) => d.id !== dish.id));
  }

  const shown = dishes.filter((d) => dishMatches(d, query));

  return (
    <>
      {dishes.length === 0 ? (
        <div className="empty-state stacked">
          <p className="muted">
            Your own dishes — the meals you already know how to make. The planner
            picks from these first.
          </p>
          <button className="btn primary large" onClick={() => setEditing("new")}>
            + Add your first dish
          </button>
        </div>
      ) : (
        <div className="grid">
          {/* First, so adding is always one tap away on a phone. */}
          <button className="card add-tile" onClick={() => setEditing("new")}>
            + Add dish
          </button>
          {shown.map((dish) => (
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
                {excerptFor(dish) || <em className="muted">No extra detail added yet</em>}
              </p>
            </article>
          ))}
        </div>
      )}

      {editing !== null && (
        <DishEditor
          dish={editing === "new" ? null : editing}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}
    </>
  );
}
