import { createContext, useContext } from "react";
import type { Appearance, Me, PlanningSettings } from "./api";
import type { SettingsSection } from "./SettingsScreen";

// What every screen shares: the household's planning settings, and the few
// actions that tie the tabs together — jump to another tab, show a toast that
// can carry a follow-up ("Added 12 ingredients · View list"), and open the
// settings or the tilbudsavis from wherever they're relevant.

export type Tab = "plan" | "fridge" | "dishes" | "shopping";

export type ToastAction = { label: string; run: () => void };

export type Household = {
  // The signed-in user; everyone in their household shares what follows.
  me: Me;
  setMe: (me: Me) => void;
  signOut: () => Promise<void>;
  settings: PlanningSettings;
  // The household's name, mark and accent colour (Settings → Personalize).
  appearance: Appearance;
  setAppearance: (appearance: Appearance) => void;
  setSettings: (settings: PlanningSettings) => void;
  go: (tab: Tab) => void;
  notify: (message: string, action?: ToastAction) => void;
  openSettings: (section?: SettingsSection) => void;
  openOffers: () => void;
  // Re-read the tab badge (shopping rows) after a change.
  refreshCounts: () => void;
};

export const HouseholdContext = createContext<Household | null>(null);

export function useHousehold(): Household {
  const household = useContext(HouseholdContext);
  if (!household) throw new Error("useHousehold outside <App>");
  return household;
}
