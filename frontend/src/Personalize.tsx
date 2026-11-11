import { useEffect, useRef, useState } from "react";
import { saveAppearance, type Appearance } from "./api";
import { useHousehold } from "./household";

// Settings → Personalize: the household makes the app its own — a name in the
// header (and the tab title), a mark beside it, an accent colour for buttons
// and highlights. Shared by everyone in the household; empty means the app's
// own "Food Planner", carrot and orange.

export const DEFAULT_NAME = "Food Planner";
export const DEFAULT_EMOJI = "🥕";
export const DEFAULT_ACCENT = "#c1592b";

const EMOJIS = ["🥕", "🍅", "🥑", "🌶️", "🍋", "🧄", "🍲", "🥘", "🍕", "🥐", "🐟", "🏡"];

// Each dark enough to carry white button text.
const ACCENTS: { colour: string; name: string }[] = [
  { colour: DEFAULT_ACCENT, name: "Carrot" },
  { colour: "#b83232", name: "Tomato" },
  { colour: "#a63d73", name: "Berry" },
  { colour: "#6d4aa8", name: "Plum" },
  { colour: "#2b6cb0", name: "Ocean" },
  { colour: "#2e7d6b", name: "Teal" },
  { colour: "#4f7f2a", name: "Herb" },
  { colour: "#946a0a", name: "Mustard" },
  { colour: "#4a5563", name: "Slate" },
];

// Puts an appearance on the page: the accent as the --accent token, the name
// as the tab title and the mark as the favicon. The installed app's
// home-screen icon is fixed by the manifest and stays the carrot.
export function applyAppearance(appearance: Appearance | null): void {
  const root = document.documentElement;
  root.style.setProperty("--accent", appearance?.accent ?? DEFAULT_ACCENT);
  document.title = appearance?.name ?? DEFAULT_NAME;
  const emoji = appearance?.emoji ?? DEFAULT_EMOJI;
  const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (icon) {
    icon.href =
      "data:image/svg+xml," +
      encodeURIComponent(
        `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>${emoji}</text></svg>`,
      );
  }
}

export function PersonalizeCard() {
  const { appearance, setAppearance, notify } = useHousehold();
  const [draft, setDraft] = useState<Appearance>(appearance);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Closing Settings without saving puts the saved look back.
  const saved = useRef(appearance);
  saved.current = appearance;
  useEffect(() => () => applyAppearance(saved.current), []);

  const accent = draft.accent ?? DEFAULT_ACCENT;
  const emoji = draft.emoji ?? DEFAULT_EMOJI;
  const changed =
    draft.name !== appearance.name ||
    draft.emoji !== appearance.emoji ||
    draft.accent !== appearance.accent;

  // Try a colour or mark on the real page while choosing; Save keeps it.
  function patch(fields: Partial<Appearance>) {
    const next = { ...draft, ...fields };
    setDraft(next);
    applyAppearance(next);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const saved = await saveAppearance({ ...draft, name: draft.name?.trim() || null });
      setAppearance(saved);
      setDraft(saved);
      notify("Looking good");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function undo() {
    setDraft(appearance);
    applyAppearance(appearance);
  }

  return (
    <section className="settings-card personalize-card">
      <label htmlFor="household-name">Personalize</label>
      <p className="muted">How the app looks for everyone in the household.</p>

      <div className="personalize-preview" style={{ borderColor: accent }}>
        <span className="brand-mark">{emoji}</span>
        <strong>{draft.name?.trim() || DEFAULT_NAME}</strong>
        <span className="personalize-sample" style={{ background: accent }}>
          ⚡ Suggest dishes
        </span>
      </div>

      <label className="field">
        <span className="field-label">Name</span>
        <input
          id="household-name"
          className="input"
          maxLength={40}
          placeholder={`${DEFAULT_NAME} — or e.g. “The Burrow kitchen”`}
          value={draft.name ?? ""}
          onChange={(e) => patch({ name: e.target.value || null })}
        />
      </label>

      <div className="field">
        <span className="field-label">Mark</span>
        <div className="emoji-grid" role="radiogroup" aria-label="Mark">
          {EMOJIS.map((e) => (
            <button
              key={e}
              type="button"
              role="radio"
              aria-checked={emoji === e}
              className={`emoji-pick${emoji === e ? " on" : ""}`}
              onClick={() => patch({ emoji: e === DEFAULT_EMOJI ? null : e })}
            >
              {e}
            </button>
          ))}
          <input
            className="input emoji-own"
            aria-label="Your own emoji"
            placeholder="Own"
            maxLength={16}
            value={EMOJIS.includes(emoji) ? "" : emoji}
            onChange={(e) => patch({ emoji: e.target.value.trim() || null })}
          />
        </div>
      </div>

      <div className="field">
        <span className="field-label">Accent colour</span>
        <div className="swatch-grid" role="radiogroup" aria-label="Accent colour">
          {ACCENTS.map((a) => (
            <button
              key={a.colour}
              type="button"
              role="radio"
              aria-checked={accent === a.colour}
              title={a.name}
              aria-label={a.name}
              className={`swatch${accent === a.colour ? " on" : ""}`}
              style={{ background: a.colour }}
              onClick={() => patch({ accent: a.colour === DEFAULT_ACCENT ? null : a.colour })}
            />
          ))}
          <label className="swatch swatch-own" title="Your own colour">
            <input
              type="color"
              aria-label="Your own colour"
              value={accent}
              onChange={(e) => patch({ accent: e.target.value })}
            />
          </label>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      <div className="account-actions">
        <button
          type="button"
          className="btn primary"
          disabled={busy || !changed}
          onClick={() => void save()}
        >
          {busy ? "Saving…" : "Save look"}
        </button>
        {changed && (
          <button type="button" className="link-btn" onClick={undo}>
            Undo
          </button>
        )}
      </div>
    </section>
  );
}
