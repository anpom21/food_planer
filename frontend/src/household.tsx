import { createContext, useContext } from "react";
import type { PlanningSettings } from "./api";

// What every screen shares: the household's planning settings, and the few
// actions that tie the tabs together — jump to another tab, show a toast that
// can carry a follow-up ("Added 12 ingredients · View list"), and open the
// settings or the tilbudsavis from wherever they're relevant.

export type Tab = "plan" | "fridge" | "dishes" | "shopping";

export type ToastAction = { label: string; run: () => void };

export type Household = {
  settings: PlanningSettings;
  setSettings: (settings: PlanningSettings) => void;
  go: (tab: Tab) => void;
  notify: (message: string, action?: ToastAction) => void;
  openSettings: () => void;
  openOffers: () => void;
  // Re-read the tab badges (fresh items, shopping rows) after a change.
  refreshCounts: () => void;
};

export const HouseholdContext = createContext<Household | null>(null);

export function useHousehold(): Household {
  const household = useContext(HouseholdContext);
  if (!household) throw new Error("useHousehold outside <App>");
  return household;
}
