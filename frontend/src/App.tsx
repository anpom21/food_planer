import { useEffect, useState } from "react";
import {
  createDish,
  deleteDish,
  getProfile,
  identify,
  listDishes,
  listProfiles,
  replaceDish,
  type Dish,
  type DishInput,
  type Profile,
  type ProfileSummary,
} from "./api";
import { DishEditor } from "./DishEditor";
import { Fridge } from "./Fridge";
import { Offers } from "./Offers";
import { PlanWeek } from "./PlanWeek";
import { Recipes } from "./Recipes";
import { SettingsScreen } from "./SettingsScreen";
import { ShoppingList } from "./ShoppingList";
import "./app.css";

// Issue #17 — Identify yourself and switch profiles.
//
// localStorage holds one thing: `foodPlanner.profileId`, a pointer. On load we
// resolve it against the backend (the single source of truth). No pointer, or a
// pointer the backend no longer knows, falls straight back to the identify
// form — clearing browser storage costs nothing, since retyping the email
// resolves to the same Profile.

const PROFILE_ID_KEY = "foodPlanner.profileId";

const readPointer = () => localStorage.getItem(PROFILE_ID_KEY);
const writePointer = (id: string) => localStorage.setItem(PROFILE_ID_KEY, id);

// The one single-step form: email and display name, submitted together. No
// async validation while typing, no branching UI — the same form both first
// visitors and "Add a profile" land on.
function IdentifyForm({
  onIdentified,
  onCancel,
}: {
  onIdentified: (profile: Profile) => void;
  onCancel?: () => void;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onIdentified(await identify(email, name));
    } catch (e: unknown) {
      setError(String(e));
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: "0.75rem", maxWidth: 320 }}>
      <label style={{ display: "grid", gap: "0.25rem" }}>
        Email
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />
      </label>
      <label style={{ display: "grid", gap: "0.25rem" }}>
        Display name
        <input
          type="text"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Continue"}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        )}
      </div>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
    </form>
  );
}

// The switcher: everyone in the household plus a trailing "Add a profile" that
// opens the same form. Picking someone swaps to their preferences immediately —
// no password, no re-auth.
function ProfileSwitcher({
  current,
  onSwitch,
  onAdd,
}: {
  current: Profile;
  onSwitch: (id: string) => void;
  onAdd: () => void;
}) {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);

  useEffect(() => {
    listProfiles()
      .then(setProfiles)
      .catch(() => setProfiles([]));
  }, [current.id]);

  return (
    <nav style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
      {profiles.map((p) => (
        <button
          key={p.id}
          onClick={() => onSwitch(p.id)}
          aria-current={p.id === current.id}
          style={{ fontWeight: p.id === current.id ? 700 : 400 }}
        >
          {p.name}
        </button>
      ))}
      <button onClick={onAdd}>+ Add a profile</button>
    </nav>
  );
}

// The Dish library screen (issue #18): a three-column card grid the household
// shares. Adding a dish takes a title and five seconds; everything else is
// optional detail behind one toggle in the editor.

// A card's excerpt is whichever optional field is filled first, in the order
// recipe → ingredients → substitutes. When the card carries no ⭐ label the
// freed row lets the excerpt run longer.
const EXCERPT_UNTAGGED = 130;
const EXCERPT_TAGGED = 70;

function excerptFor(dish: Dish): string {
  const source = dish.recipe || dish.ingredients || dish.substitutes || "";
  const limit = dish.favourite ? EXCERPT_TAGGED : EXCERPT_UNTAGGED;
  if (source.length <= limit) return source;
  return source.slice(0, limit) + "…";
}

// `null` = editor closed; a Dish = editing it; "new" = the add flow.
type EditorTarget = Dish | "new" | null;

function DishLibrary() {
  const [dishes, setDishes] = useState<Dish[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditorTarget>(null);

  useEffect(() => {
    listDishes().then(setDishes).catch((e: unknown) => setError(String(e)));
  }, []);

  async function handleSave(input: DishInput) {
    const saved =
      editing && editing !== "new"
        ? await replaceDish(editing.id, input)
        : await createDish(input);
    setDishes((prev) => {
      const rest = (prev ?? []).filter((d) => d.id !== saved.id);
      return [...rest, saved];
    });
    setEditing(null);
  }

  async function handleDelete(dish: Dish) {
    // A trash icon, distinct from the click-to-edit card, deletes only after
    // an explicit confirm so a mis-click can't lose a Dish.
    if (!window.confirm(`Delete "${dish.title}"?`)) return;
    await deleteDish(dish.id);
    setDishes((prev) => (prev ?? []).filter((d) => d.id !== dish.id));
  }

  if (error) {
    return (
      <section className="library">
        <p className="error">Could not load the Dish library: {error}</p>
      </section>
    );
  }

  if (dishes === null) {
    return (
      <section className="library">
        <p className="muted">Loading…</p>
      </section>
    );
  }

  return (
    <section className="library">
      <header className="toolbar">
        <div>
          <h1>Dish library</h1>
          <p className="muted">The meals your household already knows how to make.</p>
        </div>
        <button className="btn primary" onClick={() => setEditing("new")}>
          + Add Dish
        </button>
      </header>

      {dishes.length === 0 ? (
        <div className="empty-state">
          <button className="btn primary large" onClick={() => setEditing("new")}>
            + Add your first dish
          </button>
        </div>
      ) : (
        <div className="grid">
          {dishes.map((dish) => (
            <article
              key={dish.id}
              className="card"
              role="button"
              tabIndex={0}
              onClick={() => setEditing(dish)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setEditing(dish);
                }
              }}
            >
              <button
                className="card-delete"
                title="Delete"
                aria-label={`Delete ${dish.title}`}
                onClick={(e) => {
                  e.stopPropagation();
                  void handleDelete(dish);
                }}
              >
                🗑
              </button>
              <h2 className="card-title">{dish.title}</h2>
              {dish.favourite && <span className="fav-label">⭐ Favourite</span>}
              <p className="card-excerpt">
                {excerptFor(dish) || (
                  <em className="muted">No extra detail added yet</em>
                )}
              </p>
            </article>
          ))}

          {/* The dashed end-of-grid tile — a third way into the same add flow. */}
          <button
            className="card add-tile"
            onClick={() => setEditing("new")}
          >
            + Add Dish
          </button>
        </div>
      )}

      {editing !== null && (
        <DishEditor
          dish={editing === "new" ? null : editing}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}
    </section>
  );
}

type Screen =
  | "plan"
  | "fridge"
  | "library"
  | "recipes"
  | "shopping"
  | "offers"
  | "settings";

export function App() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  // Shown when there's no current profile, or when "Add a profile" is picked.
  const [identifying, setIdentifying] = useState(false);
  const [screen, setScreen] = useState<Screen>("plan");

  // Resolve the stored pointer on load.
  useEffect(() => {
    const id = readPointer();
    if (!id) {
      setLoading(false);
      return;
    }
    getProfile(id)
      .then((p) => {
        if (p) setProfile(p);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const adopt = (p: Profile) => {
    writePointer(p.id);
    setProfile(p);
    setIdentifying(false);
  };

  const switchTo = async (id: string) => {
    const p = await getProfile(id);
    if (p) adopt(p);
  };

  if (loading) {
    return <main style={shellStyle}>Loading…</main>;
  }

  // First visit, cleared storage, or "Add a profile" — the same single form.
  if (!profile || identifying) {
    return (
      <main style={shellStyle}>
        <h1>Food Planner</h1>
        <p>Type your email and a display name to get started.</p>
        <IdentifyForm
          onIdentified={adopt}
          onCancel={profile ? () => setIdentifying(false) : undefined}
        />
      </main>
    );
  }

  return (
    <main style={shellStyle}>
      <h1>Food Planner</h1>
      <ProfileSwitcher
        current={profile}
        onSwitch={switchTo}
        onAdd={() => setIdentifying(true)}
      />
      <p>
        Signed in as <strong>{profile.name}</strong> ({profile.email}).
      </p>
      <nav style={{ display: "flex", gap: "0.5rem" }}>
        <button
          onClick={() => setScreen("plan")}
          aria-current={screen === "plan"}
          style={{ fontWeight: screen === "plan" ? 700 : 400 }}
        >
          Plan a week
        </button>
        <button
          onClick={() => setScreen("fridge")}
          aria-current={screen === "fridge"}
          style={{ fontWeight: screen === "fridge" ? 700 : 400 }}
        >
          What is in the fridge?
        </button>
        <button
          onClick={() => setScreen("library")}
          aria-current={screen === "library"}
          style={{ fontWeight: screen === "library" ? 700 : 400 }}
        >
          Dish library
        </button>
        <button
          onClick={() => setScreen("recipes")}
          aria-current={screen === "recipes"}
          style={{ fontWeight: screen === "recipes" ? 700 : 400 }}
        >
          Inspiration
        </button>
        <button
          onClick={() => setScreen("shopping")}
          aria-current={screen === "shopping"}
          style={{ fontWeight: screen === "shopping" ? 700 : 400 }}
        >
          Shopping list
        </button>
        <button
          onClick={() => setScreen("offers")}
          aria-current={screen === "offers"}
          style={{ fontWeight: screen === "offers" ? 700 : 400 }}
        >
          Tilbudsavis
        </button>
        <button
          onClick={() => setScreen("settings")}
          aria-current={screen === "settings"}
          style={{ fontWeight: screen === "settings" ? 700 : 400 }}
        >
          Settings
        </button>
      </nav>
      {screen === "plan" && (
        <PlanWeek key={profile.id} profile={profile} onSettingsSaved={setProfile} />
      )}
      {screen === "fridge" && <Fridge />}
      {screen === "library" && <DishLibrary />}
      {screen === "recipes" && <Recipes key={profile.id} profile={profile} />}
      {screen === "shopping" && <ShoppingList />}
      {screen === "offers" && <Offers key={profile.id} profile={profile} />}
      {screen === "settings" && (
        <SettingsScreen key={profile.id} profile={profile} />
      )}
    </main>
  );
}

const shellStyle: React.CSSProperties = {
  fontFamily: "system-ui",
  padding: "2rem",
  display: "grid",
  gap: "1rem",
  justifyItems: "start",
};
