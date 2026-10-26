import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  getFridge,
  getSettings,
  getShoppingList,
  type PlanningSettings,
} from "./api";
import { Dishes } from "./Dishes";
import { Fridge } from "./Fridge";
import { HouseholdContext, type Household, type Tab, type ToastAction } from "./household";
import { Offers } from "./Offers";
import { PlanWeek } from "./PlanWeek";
import { SettingsPanel } from "./SettingsScreen";
import { Sheet } from "./Sheet";
import { ShoppingList } from "./ShoppingList";
import "./app.css";
import "./shell.css";

// The app shell: four tabs — plan the week, what's in the fridge, dishes,
// the shopping list — with settings behind the ⚙. On a phone the tabs sit in
// a bottom bar under your thumb; on a wider screen they're in the header. The
// tab lives in the URL hash so reload and the back button keep your place.
//
// One household, no profiles: everyone shares the same settings, fridge,
// dishes and list.

const ICONS: Record<Tab | "settings", ReactNode> = {
  plan: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="15" rx="2.5" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </svg>
  ),
  fridge: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="5.5" y="2.5" width="13" height="19" rx="2.5" />
      <path d="M5.5 10h13M9 6v2M9 13v3" />
    </svg>
  ),
  dishes: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 12h18a9 9 0 0 1-18 0Z" />
      <path d="M9 8c0-1.5 1-2 1-3.5M13 8c0-1.5 1-2 1-3.5" />
    </svg>
  ),
  shopping: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 4h2.5l2.2 11h10.6l2-8H6.6" />
      <circle cx="9.5" cy="19" r="1.4" />
      <circle cx="17" cy="19" r="1.4" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
    </svg>
  ),
};

const TABS: { tab: Tab; label: string; short: string }[] = [
  { tab: "plan", label: "Plan my week", short: "Plan" },
  { tab: "fridge", label: "What is in the fridge", short: "Fridge" },
  { tab: "dishes", label: "Dishes", short: "Dishes" },
  { tab: "shopping", label: "Shopping list", short: "Shopping" },
];

const isTab = (value: string): value is Tab => TABS.some((t) => t.tab === value);
const tabFromHash = (): Tab => {
  const hash = window.location.hash.slice(1);
  return isTab(hash) ? hash : "plan";
};

type Toast = { id: number; message: string; action?: ToastAction };

function TabButtons({
  tab,
  counts,
  onPick,
  short,
}: {
  tab: Tab;
  counts: Partial<Record<Tab, number>>;
  onPick: (tab: Tab) => void;
  short: boolean;
}) {
  return (
    <>
      {TABS.map((t) => (
        <button
          key={t.tab}
          className={`tab${tab === t.tab ? " on" : ""}`}
          aria-current={tab === t.tab ? "page" : undefined}
          onClick={() => onPick(t.tab)}
        >
          <span className="tab-icon">
            {ICONS[t.tab]}
            {counts[t.tab] ? <span className="tab-badge">{counts[t.tab]}</span> : null}
          </span>
          <span className="tab-label">{short ? t.short : t.label}</span>
        </button>
      ))}
    </>
  );
}

export function App() {
  const [settings, setSettings] = useState<PlanningSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [offersOpen, setOffersOpen] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [counts, setCounts] = useState<Partial<Record<Tab, number>>>({});
  const toastTimer = useRef<number>();

  const loadSettings = useCallback(() => {
    setLoadError(null);
    getSettings()
      .then(setSettings)
      .catch((e: unknown) => setLoadError(String(e)));
  }, []);

  const refreshCounts = useCallback(() => {
    getFridge()
      .then((f) => setCounts((c) => ({ ...c, fridge: f.fresh.length })))
      .catch(() => undefined);
    getShoppingList()
      .then((rows) => setCounts((c) => ({ ...c, shopping: rows.length })))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    loadSettings();
    refreshCounts();
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [loadSettings, refreshCounts]);

  const go = useCallback((next: Tab) => {
    if (window.location.hash.slice(1) !== next) window.location.hash = next;
    setTab(next);
    window.scrollTo({ top: 0 });
  }, []);

  const notify = useCallback((message: string, action?: ToastAction) => {
    window.clearTimeout(toastTimer.current);
    setToast({ id: Date.now(), message, action });
    toastTimer.current = window.setTimeout(() => setToast(null), action ? 4500 : 2600);
  }, []);

  const household = useMemo<Household | null>(
    () =>
      settings && {
        settings,
        setSettings,
        go,
        notify,
        openSettings: () => setSettingsOpen(true),
        openOffers: () => setOffersOpen(true),
        refreshCounts,
      },
    [settings, go, notify, refreshCounts],
  );

  if (!household) {
    return (
      <div className="splash">
        <div className="brand-mark">🥕</div>
        {loadError ? (
          <>
            <p className="error">Could not reach the planner: {loadError}</p>
            <button className="btn" onClick={loadSettings}>
              Try again
            </button>
          </>
        ) : (
          <p className="muted">Loading…</p>
        )}
      </div>
    );
  }

  return (
    <HouseholdContext.Provider value={household}>
      <div className="shell">
        <header className="topbar">
          <button className="brand" onClick={() => go("plan")}>
            <span className="brand-mark">🥕</span>
            <span className="brand-name">Food Planner</span>
          </button>
          <nav className="tabs-top" aria-label="Sections">
            <TabButtons tab={tab} counts={counts} onPick={go} short={false} />
          </nav>
          <button
            className="icon-btn settings-btn"
            onClick={() => setSettingsOpen(true)}
            aria-label="Settings"
            title="Settings"
          >
            {ICONS.settings}
          </button>
        </header>

        <main className="screen">
          {tab === "plan" && <PlanWeek />}
          {tab === "fridge" && <Fridge />}
          {tab === "dishes" && <Dishes />}
          {tab === "shopping" && <ShoppingList />}
        </main>

        <nav className="tabs-bottom" aria-label="Sections">
          <TabButtons tab={tab} counts={counts} onPick={go} short />
        </nav>

        {settingsOpen && (
          <Sheet title="Settings" onClose={() => setSettingsOpen(false)}>
            <SettingsPanel
              settings={household.settings}
              onSaved={(saved) => {
                setSettings(saved);
                notify("Settings saved");
              }}
            />
          </Sheet>
        )}

        {offersOpen && (
          <Sheet title="Tilbudsavis" wide onClose={() => setOffersOpen(false)}>
            <Offers />
          </Sheet>
        )}

        {toast && (
          <div className="toast" role="status" key={toast.id}>
            <span>✓ {toast.message}</span>
            {toast.action && (
              <button
                className="toast-action"
                onClick={() => {
                  toast.action!.run();
                  setToast(null);
                }}
              >
                {toast.action.label}
              </button>
            )}
          </div>
        )}
      </div>
    </HouseholdContext.Provider>
  );
}
