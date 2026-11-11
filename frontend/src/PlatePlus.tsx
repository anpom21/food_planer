import { useState } from "react";
import type { Suggestion } from "./api";
import { useHousehold } from "./household";
import { useMyWeekStore } from "./myWeekStore";

// The "add to My week" mark: a plate seen from above with a plus in its
// top-right corner. It sits next to the ☆ on a dish card. `on` fills the
// plate green: the dish is in this week.
export function PlatePlusIcon({ on = false }: { on?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="plate-plus-icon">
      <circle
        cx="11"
        cy="13"
        r="8.5"
        fill={on ? "var(--in-week)" : "none"}
        stroke={on ? "var(--in-week)" : "currentColor"}
        strokeWidth="1.6"
      />
      <circle
        cx="11"
        cy="13"
        r="5"
        fill="none"
        stroke={on ? "#fff" : "currentColor"}
        strokeWidth="1.3"
      />
      <circle cx="19" cy="5" r="4.6" fill="var(--accent)" stroke="#fff" strokeWidth="1.2" />
      <path d="M19 2.8v4.4M16.8 5h4.4" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

// A toggle for this week's My week: tap to add the dish (the plate turns
// green), tap again to take it out (the plate empties).
export function AddToWeekButton({
  suggestion,
  className = "",
}: {
  suggestion: Suggestion;
  className?: string;
}) {
  const { notify, go } = useHousehold();
  const { inThisWeek, add, remove } = useMyWeekStore();
  const [busy, setBusy] = useState(false);
  const entry = inThisWeek(suggestion.title);
  const on = !!entry;

  async function toggle() {
    setBusy(true);
    try {
      if (entry) {
        await remove(entry);
        notify(`“${suggestion.title}” removed from My week`);
      } else {
        await add([suggestion]);
        notify(`“${suggestion.title}” added to My week`, {
          label: "View",
          run: () => go("plan"),
        });
      }
    } catch (e: unknown) {
      notify(`Could not change My week: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const label = on
    ? `Remove ${suggestion.title} from My week`
    : `Add ${suggestion.title} to My week`;
  return (
    <button
      type="button"
      className={`plate-plus${on ? " on" : ""} ${className}`}
      disabled={busy}
      aria-pressed={on}
      aria-label={label}
      title={on ? "In My week — tap to remove" : "Add to My week"}
      onClick={(e) => {
        // On a card that opens or selects on click, this click is only ours.
        e.stopPropagation();
        void toggle();
      }}
    >
      <PlatePlusIcon on={on} />
    </button>
  );
}
