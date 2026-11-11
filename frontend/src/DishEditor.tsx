import { useEffect, useRef, useState } from "react";
import type { Dish, DishInput } from "./api";

// The add/edit flow (issue #18). One modal for both: a title, a Favourite
// toggle, and a single "+ Add more detail (optional)" toggle that reveals
// Ingredients, Substitutes and Recipe together — one reveal, not a wizard and
// not per-field accordions.

type Props = {
  dish: Dish | null; // null = creating a new Dish
  onSave: (input: DishInput) => Promise<void>;
  onCancel: () => void;
  // An existing dish gets "+ Ingredients" at the bottom: its saved ingredient
  // lines go to the shopping list review, and the dish into My week.
  onAddIngredients?: () => void;
};

function hasAnyDetail(dish: Dish | null): boolean {
  return !!(dish && (dish.ingredients || dish.substitutes || dish.recipe));
}

export function DishEditor({ dish, onSave, onCancel, onAddIngredients }: Props) {
  const [title, setTitle] = useState(dish?.title ?? "");
  const [ingredients, setIngredients] = useState(dish?.ingredients ?? "");
  const [substitutes, setSubstitutes] = useState(dish?.substitutes ?? "");
  const [recipe, setRecipe] = useState(dish?.recipe ?? "");
  const [favourite, setFavourite] = useState(dish?.favourite ?? false);
  // Re-opening a Dish that already has any detail opens with it expanded, so
  // you don't click a toggle to see what you already wrote.
  const [showDetail, setShowDetail] = useState(hasAnyDetail(dish));
  const [saving, setSaving] = useState(false);

  const titleRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const canSave = title.trim().length > 0 && !saving;

  async function submit() {
    if (!canSave) return;
    setSaving(true);
    // Empty optional fields go up as null: with PUT being a full replace this
    // is what clears a previously-filled field.
    const trimmed = (v: string): string | null => (v.trim() ? v : null);
    try {
      await onSave({
        title: title.trim(),
        ingredients: trimmed(ingredients),
        substitutes: trimmed(substitutes),
        recipe: trimmed(recipe),
        favourite,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={dish ? "Edit dish" : "Add dish"}
        onClick={(e) => e.stopPropagation()}
      >
        <label className="field">
          <span className="field-label">Title</span>
          <input
            ref={titleRef}
            className="input"
            value={title}
            placeholder="e.g. Lasagne"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
          />
        </label>

        <button
          type="button"
          className={favourite ? "fav-toggle on" : "fav-toggle"}
          aria-pressed={favourite}
          onClick={() => setFavourite((v) => !v)}
        >
          ⭐ Favourite
        </button>

        {showDetail ? (
          <div className="detail">
            <label className="field">
              <span className="field-label">Ingredients</span>
              <span className="field-caption">optional</span>
              <textarea
                className="textarea"
                value={ingredients}
                onChange={(e) => setIngredients(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field-label">Substitutes</span>
              <span className="field-caption">optional</span>
              <textarea
                className="textarea"
                value={substitutes}
                onChange={(e) => setSubstitutes(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field-label">Recipe</span>
              <span className="field-caption">optional</span>
              <textarea
                className="textarea"
                value={recipe}
                onChange={(e) => setRecipe(e.target.value)}
              />
            </label>
          </div>
        ) : (
          <button
            type="button"
            className="detail-toggle"
            onClick={() => setShowDetail(true)}
          >
            + Add more detail (optional)
          </button>
        )}

        <div className="modal-actions">
          {onAddIngredients && (
            <button
              className="btn add-ingredients-left"
              onClick={onAddIngredients}
              disabled={!dish?.ingredients?.trim()}
              title={
                dish?.ingredients?.trim()
                  ? "Add the saved ingredients to the shopping list"
                  : "Write down some ingredients first"
              }
            >
              + Ingredients
            </button>
          )}
          <button className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn primary" disabled={!canSave} onClick={() => void submit()}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
