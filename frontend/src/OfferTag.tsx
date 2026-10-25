import { useState } from "react";
import type { Discount, SuggestionIngredient } from "./api";

// The 🏷️ marker on an ingredient that's on offer this week. Hovering, focusing
// or tapping it opens a card with the exact offer the plan drew on — the
// tilbudsavis image, price, pack size and dates. The card is fixed-positioned
// from the tag's own box, so a scrolling modal can't clip it.

const kr = new Intl.NumberFormat("da-DK", { style: "currency", currency: "DKK" });

function shortDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("da-DK", {
    day: "numeric",
    month: "short",
  });
}

const norm = (s: string) => s.toLowerCase().trim();

// The offer covering an ingredient: the model names it exactly as listed, with
// a containment fallback for small slips ("løg" vs "rødløg").
export function offerFor(
  ingredient: SuggestionIngredient,
  discounts: Discount[],
): Discount | undefined {
  const name = norm(ingredient.name);
  const named = discounts.filter((d) => d.matchedIngredient);
  return (
    named.find((d) => norm(d.matchedIngredient!) === name) ??
    named.find((d) => {
      const m = norm(d.matchedIngredient!);
      return name.includes(m) || m.includes(name);
    })
  );
}

export function OfferCard({ offer }: { offer: Discount }) {
  return (
    <div className="offer-pop-card">
      {offer.imageUrl && <img src={offer.imageUrl} alt="" />}
      <div className="offer-pop-body">
        <strong>{offer.productName}</strong>
        <span className="muted">
          {offer.shop}
          {offer.unitSize ? ` · ${offer.unitSize}` : ""}
        </span>
        <span className="offer-price">
          {offer.price !== null && <strong>{kr.format(offer.price)}</strong>}
          {offer.originalPrice !== null && <s>{kr.format(offer.originalPrice)}</s>}
          {offer.discountPercent !== null && (
            <span className="chip discount">−{Math.round(offer.discountPercent)}%</span>
          )}
        </span>
        {offer.validUntil && (
          <span className="muted">
            {offer.validFrom ? `${shortDate(offer.validFrom)} – ` : "until "}
            {shortDate(offer.validUntil)}
          </span>
        )}
      </div>
    </div>
  );
}

export function OfferTag({ offer }: { offer: Discount }) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const [pinned, setPinned] = useState(false);

  const show = (el: HTMLElement) => {
    const box = el.getBoundingClientRect();
    // Below the tag, nudged left so it stays on screen at the right edge.
    const left = Math.max(8, Math.min(box.left, window.innerWidth - 300));
    const below = box.bottom + 6;
    const top = below + 320 > window.innerHeight ? Math.max(8, box.top - 326) : below;
    setAt({ top, left });
  };
  const hide = () => {
    if (!pinned) setAt(null);
  };

  return (
    <span
      className="offer-tag"
      role="button"
      tabIndex={0}
      aria-label={`On offer: ${offer.productName}, ${offer.shop}`}
      onMouseEnter={(e) => show(e.currentTarget)}
      onMouseLeave={hide}
      onFocus={(e) => show(e.currentTarget)}
      onBlur={() => {
        setPinned(false);
        setAt(null);
      }}
      // Inside a review row's <label>, a click must not tick the checkbox.
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (pinned) {
          setPinned(false);
          setAt(null);
        } else {
          setPinned(true);
          show(e.currentTarget);
        }
      }}
    >
      🏷️
      {at && (
        <span className="offer-pop" style={{ top: at.top, left: at.left }}>
          <OfferCard offer={offer} />
        </span>
      )}
    </span>
  );
}
