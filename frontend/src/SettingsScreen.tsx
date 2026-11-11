import { useEffect, useState } from "react";
import {
  listShops,
  saveSettings,
  type RecipeMode,
  shopIconUrl,
  type PlanningSettings,
  type Shop,
} from "./api";
import { AccountCard } from "./AccountCard";
import { HouseholdCard } from "./HouseholdCard";
import { InstallCard } from "./InstallCard";
import { PersonalizeCard } from "./Personalize";
import { ModelSettingsCard } from "./ModelSettings";
import { PromptEditor } from "./PromptEditor";

// The Settings sheet, opened from the ⚙ in the header. The settled behavioural
// reference is the prototype's recommended variant (prototype/settings-screen,
// "variant D"): a boxed layout of one card holding days-to-plan,
// suggestions-per-day and the known-vs-unknown lean together; one card holding
// the priority order as a drag-to-reorder list; and a full-width Inspiration
// textarea. Preferred shops are a separate ticket and deliberately absent here.
//
// Settings are one household-wide set, saved together via PUT /api/settings.

// The four priorities in a stable display order, keyed by the value stored in
// settings.priority. Order in the list expresses what matters most, so no
// numeric weights are guessed at.
const PRIORITY_LABELS: Record<string, string> = {
  cheap: "Cheap",
  quick: "Quick & easy",
  delicious: "Delicious",
  healthy: "Healthy",
};

// A narrow number box with − and + buttons inside one bordered pill, rather
// than the native browser spinner, which is miserable on a tablet.
export function Stepper({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  const clamp = (n: number) => Math.max(min, Math.min(max, n));
  return (
    <div className="field">
      <label>{label}</label>
      <div className="stepper">
        <button
          type="button"
          className="step-btn"
          aria-label={`Decrease ${label}`}
          onClick={() => onChange(clamp(value - 1))}
        >
          −
        </button>
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(clamp(Number(e.target.value) || 0))}
        />
        <button
          type="button"
          className="step-btn"
          aria-label={`Increase ${label}`}
          onClick={() => onChange(clamp(value + 1))}
        >
          +
        </button>
      </div>
    </div>
  );
}

// The known-vs-unknown lean as a labelled slider. Shared by the Settings screen
// and the per-run override modal so both render and write the bias identically.
export function BiasSlider({
  id,
  value,
  onChange,
}: {
  id: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>Known vs. unknown dishes</label>
      <input
        id={id}
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className="slider-labels">
        <span>Mostly known</span>
        <span>Mostly unknown</span>
      </div>
    </div>
  );
}

// A chain with no logo file yet gets an automatic coloured-initial badge, so
// the pill still reads at a glance. Colour is derived from the slug (stable per
// chain); initials are the first two letters of the name.
function badgeColour(slug: string): string {
  let hue = 0;
  for (let i = 0; i < slug.length; i++) hue = (hue * 31 + slug.charCodeAt(i)) % 360;
  return `hsl(${hue}, 52%, 42%)`;
}

function initials(name: string): string {
  const letters = name.replace(/[^A-Za-z]/g, "");
  return (letters.slice(0, 2) || name.slice(0, 2)).toUpperCase();
}

// A chain's logo, or its coloured-initial badge when there's no logo file.
// Shared by the preferred-shops picker and the tilbudsavis screen.
export function ShopMark({ shop }: { shop: Shop }) {
  return shop.hasIcon ? (
    <img
      className="shop-logo"
      src={shopIconUrl(shop.slug)}
      alt=""
      aria-hidden="true"
    />
  ) : (
    <span
      className="shop-badge"
      aria-hidden="true"
      style={{ background: badgeColour(shop.slug) }}
    >
      {initials(shop.name)}
    </span>
  );
}

// The preferred-shops picker (issue #32/#33/#34): a full-width card of pills
// over the fixed Danish-chain list, each carrying its logo (or a coloured
// initial when hasIcon is false — no failed image request), plus an "Other…"
// pill revealing a free-text field so an unlisted local shop isn't locked out.
//
// Selected shops live in settings.shops as a flat list: catalog slugs for the
// known chains, plus whatever free text was typed under "Other…". Anything in
// the list that isn't a catalog slug is an "other" entry.
function ShopPicker({
  shops,
  onChange,
}: {
  shops: string[];
  onChange: (shops: string[]) => void;
}) {
  const [catalog, setCatalog] = useState<Shop[] | null>(null);
  const [otherOpen, setOtherOpen] = useState(false);
  const [otherText, setOtherText] = useState("");

  // Split the stored shops against the catalog: known chains keep their pill
  // selected, anything else is a free-text "other" entry.
  const catalogSlugs = new Set((catalog ?? []).map((s) => s.slug));
  const knownSelected = shops.filter((s) => catalogSlugs.has(s));
  const others = shops.filter((s) => !catalogSlugs.has(s));

  useEffect(() => {
    listShops()
      .then(setCatalog)
      .catch(() => setCatalog([]));
  }, []);

  // Once the catalog is known, reflect any stored "other" entries into the open
  // state and the text field so re-opening the screen shows what's saved.
  useEffect(() => {
    if (catalog === null) return;
    if (others.length) {
      setOtherOpen(true);
      setOtherText(others.join(", "));
    }
    // Only seed from the catalog arriving, not on each keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  const toggleChain = (slug: string) => {
    const next = shops.includes(slug)
      ? shops.filter((s) => s !== slug)
      : [...shops, slug];
    onChange(next);
  };

  const applyOther = (text: string) => {
    setOtherText(text);
    const parsed = text
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    onChange([...knownSelected, ...parsed]);
  };

  const toggleOther = () => {
    if (otherOpen) {
      setOtherOpen(false);
      setOtherText("");
      onChange(knownSelected); // drop any free-text entries
    } else {
      setOtherOpen(true);
    }
  };

  const otherSelected = otherOpen || others.length > 0;

  return (
    <section className="settings-card">
      <label>
        Preferred shops{" "}
        <span className="hint">— pick the chains you actually shop at</span>
      </label>
      <div className="pill-grid">
        {(catalog ?? []).map((shop) => {
          const selected = shops.includes(shop.slug);
          return (
            <button
              type="button"
              key={shop.slug}
              className={selected ? "shop-pill selected" : "shop-pill"}
              aria-pressed={selected}
              onClick={() => toggleChain(shop.slug)}
            >
              <ShopMark shop={shop} />
              {shop.name}
            </button>
          );
        })}
        <button
          type="button"
          className={otherSelected ? "shop-pill selected" : "shop-pill"}
          aria-pressed={otherSelected}
          onClick={toggleOther}
        >
          Other…
        </button>
      </div>
      {otherSelected && (
        <input
          className="other-shop-input"
          type="text"
          placeholder="e.g. the corner grocer (comma-separated)"
          value={otherText}
          onChange={(e) => applyOther(e.target.value)}
        />
      )}
    </section>
  );
}

// The three ways the planner can use imported online recipes.
const RECIPE_MODES: { mode: RecipeMode; label: string; hint: string }[] = [
  { mode: "only", label: "Only online recipes", hint: "every dish is a recipe" },
  { mode: "mix", label: "Half and half", hint: "about half the dishes" },
  { mode: "none", label: "No online recipes", hint: "library and new dishes only" },
];

// The planning settings as a set of cards over a draft: days and the
// known-vs-unknown lean, the priority order, shops, online recipes and
// Inspiration. Shared by the Settings sheet (which saves them as the defaults)
// and the Suggest dishes sheet (which plans with them).
export function PlanningFields({
  draft,
  onChange,
}: {
  draft: PlanningSettings;
  onChange: (fields: Partial<PlanningSettings>) => void;
}) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  // Reorder by dragging (a mouse), or with the ↑ ↓ buttons (a phone, where
  // HTML drag and drop doesn't reach). The saved order is exactly the four
  // items as they end up here.
  const movePriority = (from: number, to: number) => {
    if (from === to || to < 0 || to >= draft.priority.length) return;
    const priority = [...draft.priority];
    const [moved] = priority.splice(from, 1);
    priority.splice(to, 0, moved);
    onChange({ priority });
  };

  return (
    <>
      <section className="settings-card">
        <div className="row">
          <Stepper
            label="Days to plan"
            value={draft.daysToPlan}
            min={1}
            max={14}
            onChange={(daysToPlan) => onChange({ daysToPlan })}
          />
          <Stepper
            label="Suggestions / day"
            value={draft.suggestionsPerDay}
            min={1}
            max={10}
            onChange={(suggestionsPerDay) => onChange({ suggestionsPerDay })}
          />
        </div>
        <BiasSlider
          id="known-vs-unknown"
          value={draft.knownVsUnknownBias}
          onChange={(knownVsUnknownBias) => onChange({ knownVsUnknownBias })}
        />
      </section>

      <section className="settings-card">
        <label>
          Priority order <span className="hint">(top = matters most)</span>
        </label>
        <ul className="drag-list">
          {draft.priority.map((key, index) => (
            <li
              key={key}
              draggable
              className={dragIndex === index ? "dragging" : undefined}
              onDragStart={() => setDragIndex(index)}
              onDragEnd={() => setDragIndex(null)}
              onDragOver={(e) => {
                e.preventDefault();
                if (dragIndex !== null && dragIndex !== index) {
                  movePriority(dragIndex, index);
                  setDragIndex(index);
                }
              }}
            >
              <span className="rank-num">{index + 1}</span>
              <span className="grip" aria-hidden="true">
                ⠿
              </span>
              <span className="rank-label">{PRIORITY_LABELS[key] ?? key}</span>
              <span className="rank-moves">
                <button
                  type="button"
                  className="rank-move"
                  aria-label={`Move ${PRIORITY_LABELS[key] ?? key} up`}
                  disabled={index === 0}
                  onClick={() => movePriority(index, index - 1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="rank-move"
                  aria-label={`Move ${PRIORITY_LABELS[key] ?? key} down`}
                  disabled={index === draft.priority.length - 1}
                  onClick={() => movePriority(index, index + 1)}
                >
                  ↓
                </button>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <ShopPicker shops={draft.shops} onChange={(shops) => onChange({ shops })} />

      <section className="settings-card">
        <label>
          Online recipes{" "}
          <span className="hint">— dishes taken 1:1 from imported recipes</span>
        </label>
        <div className="mode-pills" role="radiogroup" aria-label="Online recipes">
          {RECIPE_MODES.map(({ mode, label, hint }) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={(draft.recipeMode ?? "mix") === mode}
              className={`mode-pill${(draft.recipeMode ?? "mix") === mode ? " on" : ""}`}
              onClick={() => onChange({ recipeMode: mode })}
            >
              <strong>{label}</strong>
              <span>{hint}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="settings-card">
        <label htmlFor="inspiration">
          Inspiration{" "}
          <span className="hint">— steer invented dishes in your own words</span>
        </label>
        <textarea
          id="inspiration"
          placeholder="e.g. more Vietnamese food, less pasta"
          value={draft.inspiration}
          onChange={(e) => onChange({ inspiration: e.target.value })}
        />
      </section>
    </>
  );
}

// The household's planning settings, edited as a draft and saved together.
export function PlanningSettingsForm({
  settings,
  onSaved,
}: {
  settings: PlanningSettings;
  onSaved: (settings: PlanningSettings) => void;
}) {
  // The draft is the working copy; nothing persists until Save. Starting from
  // the stored settings means the form reflects what's on disk.
  const [draft, setDraft] = useState<PlanningSettings>(settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const patch = (fields: Partial<PlanningSettings>) => {
    setDraft((prev) => ({ ...prev, ...fields }));
    setSaved(false);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await saveSettings(draft);
      onSaved(updated);
      setSaved(true);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="settings" onSubmit={submit}>
      <h3 className="settings-heading">Planning defaults</h3>
      <p className="muted">
        What every plan starts from. ⚡ Suggest dishes on the My week tab lets
        you bend them for a single plan.
      </p>

      <PlanningFields draft={draft} onChange={patch} />

      <div className="settings-actions">
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save settings"}
        </button>
        {saved && <span className="saved-note">Saved ✓</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </form>
  );
}

// What the ⚙ opens, in three parts: the household (who's signed in, who else
// is in it, how the app looks, installing it), the planning defaults and the
// prompt behind them, and the model.
export type SettingsSection = "household" | "planning" | "model";

const SECTIONS: { section: SettingsSection; label: string }[] = [
  { section: "household", label: "Household" },
  { section: "planning", label: "Planning" },
  { section: "model", label: "Model" },
];

export function SettingsPanel({
  settings,
  onSaved,
  initialSection = "household",
}: {
  settings: PlanningSettings;
  onSaved: (settings: PlanningSettings) => void;
  initialSection?: SettingsSection;
}) {
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [promptOpen, setPromptOpen] = useState(false);
  return (
    <div className="settings-panel">
      <div className="segmented settings-sections" role="tablist">
        {SECTIONS.map((s) => (
          <button
            key={s.section}
            type="button"
            role="tab"
            aria-selected={section === s.section}
            className={section === s.section ? "on" : ""}
            onClick={() => setSection(s.section)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {section === "household" && (
        <div className="settings settings-stack">
          <AccountCard />
          <HouseholdCard />
          <PersonalizeCard />
          <InstallCard />
        </div>
      )}

      {section === "planning" && (
        <>
          <PlanningSettingsForm settings={settings} onSaved={onSaved} />
          <section className="settings-card prompt-card">
            <div>
              <label>Planner prompt</label>
              <p className="muted">
                The instructions sent to the model, with these settings filled in
                wherever a <code className="var-token">{"{{variable}}"}</code> appears.
              </p>
            </div>
            <button type="button" className="btn" onClick={() => setPromptOpen(true)}>
              Edit prompt…
            </button>
          </section>
        </>
      )}

      {section === "model" && <ModelSettingsCard />}

      {promptOpen && <PromptEditor onClose={() => setPromptOpen(false)} />}
    </div>
  );
}
