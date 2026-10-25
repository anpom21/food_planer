import type { OnHand } from "./api";
import "./onhand.css";

// Marks an ingredient we already have, so fridge items and pantry staples read
// differently from what needs buying: green for something fresh in the fridge
// (use it up), grey-blue for a staple that's always in the cupboard.

const LABEL = { fresh: "I køleskabet", staple: "I skabet" } as const;
const ICON = { fresh: "🥬", staple: "🫙" } as const;

export function OnHandBadge({ have }: { have?: OnHand }) {
  if (!have) return null;
  return (
    <span className={`onhand ${have}`} title={LABEL[have]}>
      {ICON[have]} {LABEL[have]}
    </span>
  );
}
