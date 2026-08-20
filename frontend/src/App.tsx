import { useEffect, useState } from "react";
import {
  getProfile,
  identify,
  listProfiles,
  type Profile,
  type ProfileSummary,
} from "./api";

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

export function App() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  // Shown when there's no current profile, or when "Add a profile" is picked.
  const [identifying, setIdentifying] = useState(false);

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
