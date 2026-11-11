import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  checkInvite,
  getAppearance,
  getMe,
  getSettings,
  getShoppingList,
  joinHousehold,
  signOut as postSignOut,
  SIGNED_OUT_EVENT,
  type Appearance,
  type InvitePreview,
  type Me,
  type PlanningSettings,
} from "./api";
import { Dishes } from "./Dishes";
import { Fridge } from "./Fridge";
import { HouseholdContext, type Household, type Tab, type ToastAction } from "./household";
import { MyWeekProvider } from "./myWeekStore";
import { Offers } from "./Offers";
import { PlanWeek } from "./PlanWeek";
import { applyAppearance, DEFAULT_EMOJI, DEFAULT_NAME } from "./Personalize";
import { SettingsPanel, type SettingsSection } from "./SettingsScreen";
import { Sheet } from "./Sheet";
import { ShoppingList } from "./ShoppingList";
import { SignIn } from "./SignIn";
import "./app.css";
import "./shell.css";

// The app shell: four tabs — my week (and the planner), what's in the fridge, dishes,
// the shopping list — with settings behind the ⚙. On a phone the tabs sit in
// a bottom bar under your thumb; on a wider screen they're in the header. The
// tab lives in the URL hash so reload and the back button keep your place.
//
// Everyone signed in shares their household's settings, fridge, dishes and
// list; nothing loads until someone has signed in. An invite link
// (/?invite=<token>) signs someone up into the inviter's household, or — when
// they're already signed in — offers to move them into it.

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
  { tab: "plan", label: "My week", short: "My week" },
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

// The invite token from the link this page was opened with, kept for the tab
// while the person signs up or in, and taken out of the address bar so it
// isn't bookmarked or shared further by accident.
const INVITE_KEY = "fp_invite";

function takeInviteFromUrl(): string | null {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("invite");
  if (token) {
    url.searchParams.delete("invite");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    try {
      sessionStorage.setItem(INVITE_KEY, token);
    } catch {
      // No storage: the token still lives in memory for this page.
    }
    return token;
  }
  try {
    return sessionStorage.getItem(INVITE_KEY);
  } catch {
    return null;
  }
}

function forgetInvite(): void {
  try {
    sessionStorage.removeItem(INVITE_KEY);
  } catch {
    // Nothing kept.
  }
}

// Shown to someone already signed in who opens an invite link: moving
// household is their call, and what they had stays behind.
function JoinPrompt({
  token,
  preview,
  onDone,
}: {
  token: string;
  preview: InvitePreview;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function join() {
    setBusy(true);
    setError(null);
    try {
      await joinHousehold(token);
      forgetInvite();
      // Start clean, so nothing of the old household lingers on screen.
      window.location.reload();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      if (message.startsWith("You're already")) {
        forgetInvite();
        onDone();
        return;
      }
      setError(message);
      setBusy(false);
    }
  }

  return (
    <Sheet title="Join a household" onClose={onDone}>
      <div className="join-prompt">
        <p>
          <strong>{preview.invitedBy}</strong> invited you to join{" "}
          <strong>{preview.householdName}</strong>.
        </p>
        <p className="muted">
          You'll share its fridge, dishes, My week, shopping list and settings.
          What's in your current household stays where it is, but you won't see
          it here any more.
        </p>
        {error && <p className="error">{error}</p>}
        <div className="account-actions">
          <button className="btn primary" disabled={busy} onClick={() => void join()}>
            {busy ? "Joining…" : `Join ${preview.householdName}`}
          </button>
          <button
            className="link-btn"
            onClick={() => {
              forgetInvite();
              onDone();
            }}
          >
            Not now
          </button>
        </div>
      </div>
    </Sheet>
  );
}

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
  // undefined while asking the server; null when nobody is signed in here.
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [settings, setSettings] = useState<PlanningSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [appearance, setAppearance] = useState<Appearance | null>(null);
  // The section Settings is open on, or null while it's closed.
  const [settingsOpen, setSettingsOpen] = useState<SettingsSection | null>(null);
  const [invite, setInvite] = useState<string | null>(takeInviteFromUrl);
  const [invitePreview, setInvitePreview] = useState<InvitePreview | null>(null);
  const [offersOpen, setOffersOpen] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [counts, setCounts] = useState<Partial<Record<Tab, number>>>({});
  const toastTimer = useRef<number>();

  const loadSettings = useCallback(() => {
    setLoadError(null);
    Promise.all([getSettings(), getAppearance()])
      .then(([s, a]) => {
        setSettings(s);
        setAppearance(a);
      })
      .catch((e: unknown) => setLoadError(String(e)));
  }, []);

  // The household's look on the page, as soon as it's known.
  useEffect(() => applyAppearance(appearance), [appearance]);

  // Signed in with an invite link in hand: ask whether to join.
  useEffect(() => {
    if (!me || !invite) return;
    checkInvite(invite)
      .then(setInvitePreview)
      .catch(() => {
        // Expired or revoked: nothing to offer.
        forgetInvite();
        setInvite(null);
      });
  }, [me, invite]);

  // Only the shopping list carries a count on its tab.
  const refreshCounts = useCallback(() => {
    getShoppingList()
      .then((rows) => setCounts((c) => ({ ...c, shopping: rows.length })))
      .catch(() => undefined);
  }, []);

  const checkSession = useCallback(() => {
    setLoadError(null);
    getMe()
      .then(setMe)
      .catch((e: unknown) => setLoadError(String(e)));
  }, []);

  useEffect(() => {
    checkSession();
    const onHash = () => setTab(tabFromHash());
    // The session ended elsewhere (signed out, or a password change on
    // another device): back to the sign-in screen.
    const onSignedOut = () => {
      setMe(null);
      setSettings(null);
      setAppearance(null);
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut);
    };
  }, [checkSession]);

  // Once someone is signed in, load their household.
  useEffect(() => {
    if (!me) return;
    loadSettings();
    refreshCounts();
  }, [me, loadSettings, refreshCounts]);

  // Signing out reloads the page, so nothing of this household lingers in
  // memory for whoever signs in next on the device.
  const signOut = useCallback(async () => {
    await postSignOut();
    window.location.hash = "";
    window.location.reload();
  }, []);

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
      !me || !settings || !appearance
        ? null
        : {
            me,
            setMe,
            signOut,
            settings,
            setSettings,
            appearance,
            setAppearance,
            go,
            notify,
            openSettings: (section: SettingsSection = "household") => setSettingsOpen(section),
            openOffers: () => setOffersOpen(true),
            refreshCounts,
          },
    [me, settings, appearance, go, notify, refreshCounts, signOut],
  );

  if (me === null)
    return (
      <SignIn
        invite={invite}
        onSignedIn={(signedIn, joined) => {
          // Signed up through the link: already in that household.
          if (joined) {
            forgetInvite();
            setInvite(null);
          }
          setMe(signedIn);
        }}
        onInviteGone={() => {
          forgetInvite();
          setInvite(null);
        }}
      />
    );

  if (!household) {
    return (
      <div className="splash">
        <div className="brand-mark">🥕</div>
        {loadError ? (
          <>
            <p className="error">Could not reach the planner: {loadError}</p>
            <button className="btn" onClick={me ? loadSettings : checkSession}>
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
      <MyWeekProvider>
        <div className="shell">
          <header className="topbar">
            <button className="brand" onClick={() => go("plan")}>
              <span className="brand-mark">{household.appearance.emoji ?? DEFAULT_EMOJI}</span>
              <span className="brand-name">{household.appearance.name ?? DEFAULT_NAME}</span>
            </button>
            <nav className="tabs-top" aria-label="Sections">
              <TabButtons tab={tab} counts={counts} onPick={go} short={false} />
            </nav>
            <button
              className="icon-btn settings-btn"
              onClick={() => setSettingsOpen("household")}
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
            <Sheet title="Settings" onClose={() => setSettingsOpen(null)}>
              <SettingsPanel
                initialSection={settingsOpen}
                settings={household.settings}
                onSaved={(saved) => {
                  setSettings(saved);
                  notify("Settings saved");
                }}
              />
            </Sheet>
          )}

          {invite && invitePreview && (
            <JoinPrompt
              token={invite}
              preview={invitePreview}
              onDone={() => {
                setInvite(null);
                setInvitePreview(null);
              }}
            />
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
      </MyWeekProvider>
    </HouseholdContext.Provider>
  );
}
