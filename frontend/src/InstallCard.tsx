import { useEffect, useState } from "react";

// Settings → Install on your phone: put the planner on the home screen so it
// opens full-screen like an app. Chrome and Edge on Android (and desktop)
// offer an install prompt we can trigger from a button; Safari on iOS has none,
// so there it's the Share → Add to Home Screen steps, spelled out.

type InstallPrompt = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

// The browser fires this once, early, when the app is installable; keep it
// for whenever the person opens this card.
let deferred: InstallPrompt | null = null;
const listeners = new Set<() => void>();
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferred = e as InstallPrompt;
  listeners.forEach((l) => l());
});
window.addEventListener("appinstalled", () => {
  deferred = null;
  listeners.forEach((l) => l());
});

type Platform = "ios" | "android";

function detectPlatform(): Platform {
  const ua = navigator.userAgent;
  // iPadOS reports itself as a Mac, but a Mac has no touch screen.
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  return ios ? "ios" : "android";
}

export function isInstalled(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function ShareIcon() {
  return (
    <svg className="inline-icon" viewBox="0 0 24 24" aria-label="Share">
      <path d="M12 3v12M8 7l4-4 4 4" />
      <path d="M6 11H5v10h14V11h-1" />
    </svg>
  );
}

export function InstallCard() {
  const [platform, setPlatform] = useState<Platform>(detectPlatform);
  const [prompt, setPrompt] = useState<InstallPrompt | null>(deferred);
  const [installed, setInstalled] = useState(isInstalled);

  useEffect(() => {
    const update = () => {
      setPrompt(deferred);
      setInstalled(isInstalled());
    };
    listeners.add(update);
    return () => {
      listeners.delete(update);
    };
  }, []);

  async function install() {
    if (!prompt) return;
    await prompt.prompt();
    await prompt.userChoice;
    deferred = null;
    setPrompt(null);
  }

  if (installed) {
    return (
      <section className="settings-card install-card">
        <label>Installed ✓</label>
        <p className="muted">You're using the app from your home screen.</p>
      </section>
    );
  }

  return (
    <section className="settings-card install-card">
      <label>Install on your phone</label>
      <p className="muted">
        Put the planner on your home screen: it opens full-screen, like any
        other app.
      </p>

      {prompt && (
        <button type="button" className="btn primary" onClick={() => void install()}>
          Install the app
        </button>
      )}

      <div className="segmented install-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={platform === "ios"}
          className={platform === "ios" ? "on" : ""}
          onClick={() => setPlatform("ios")}
        >
          iPhone / iPad
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={platform === "android"}
          className={platform === "android" ? "on" : ""}
          onClick={() => setPlatform("android")}
        >
          Android
        </button>
      </div>

      {platform === "ios" ? (
        <ol className="install-steps">
          <li>
            Open this page in <strong>Safari</strong>.
          </li>
          <li>
            Tap <strong>Share</strong> <ShareIcon /> — at the bottom of the
            screen on an iPhone, top right on an iPad.
          </li>
          <li>
            Scroll down and tap <strong>Add to Home Screen</strong>, then{" "}
            <strong>Add</strong>.
          </li>
          <li>
            Open the planner from its new icon and <strong>sign in once more</strong>{" "}
            — the home-screen app keeps its own sign-in, apart from Safari's.
          </li>
        </ol>
      ) : (
        <ol className="install-steps">
          <li>
            Open this page in <strong>Chrome</strong>.
          </li>
          <li>
            Tap the <strong>⋮</strong> menu, top right.
          </li>
          <li>
            Tap <strong>Install app</strong> (or <strong>Add to Home screen</strong>{" "}
            → <strong>Install</strong>).
          </li>
          <li>Open it from the new icon on your home screen or in the app drawer.</li>
        </ol>
      )}

      {platform === "android" && !window.isSecureContext && (
        <p className="muted install-note">
          This address isn't https, so Chrome may only add a shortcut that opens
          with an address bar. For the full-screen app, open the planner through
          its https address — see “Install as an app” in the README.
        </p>
      )}
    </section>
  );
}
