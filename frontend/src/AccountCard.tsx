import { useState } from "react";
import { changePassword } from "./api";
import { useHousehold } from "./household";

// Settings → Account: who is signed in, their (optional) password, and Log
// out. Changing or removing a password needs the current one, and signs the
// user's other devices out.

export function AccountCard() {
  const { me, setMe, signOut, notify } = useHousehold();
  const [editing, setEditing] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = next !== "" && repeat !== "" && next !== repeat;

  function close() {
    setEditing(false);
    setCurrent("");
    setNext("");
    setRepeat("");
    setError(null);
  }

  async function save(newPassword: string | null) {
    setBusy(true);
    setError(null);
    try {
      const updated = await changePassword(me.hasPassword ? current : null, newPassword);
      setMe(updated);
      notify(newPassword ? "Password saved" : "Password removed");
      close();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card account-card">
      <div className="account-row">
        <div>
          <label>Signed in as {me.username}</label>
          <p className="muted">
            {me.hasPassword
              ? "Protected by a password."
              : "No password — anyone who knows your username can sign in."}
          </p>
        </div>
        <button type="button" className="btn" onClick={() => void signOut()}>
          Log out
        </button>
      </div>

      {editing ? (
        <form
          className="account-password"
          onSubmit={(e) => {
            e.preventDefault();
            if (!mismatch && next) void save(next);
          }}
        >
          {me.hasPassword && (
            <label className="field">
              <span className="field-label">Current password</span>
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            </label>
          )}
          <label className="field">
            <span className="field-label">New password</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder="At least 8 characters"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">Repeat new password</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
            {mismatch && <span className="field-caption error">The passwords don't match</span>}
          </label>
          <p className="muted account-note">
            Stored only as a one-way Argon2 hash: nobody — not even whoever runs
            this server — can read it back. Your other devices will be signed out.
          </p>
          {error && <p className="error">{error}</p>}
          <div className="account-actions">
            <button
              className="btn primary"
              type="submit"
              disabled={busy || !next || next !== repeat || (me.hasPassword && !current)}
            >
              {busy ? "Saving…" : "Save password"}
            </button>
            {me.hasPassword && (
              <button
                type="button"
                className="btn"
                disabled={busy || !current}
                title="Sign in with your username alone from now on"
                onClick={() => void save(null)}
              >
                Remove password
              </button>
            )}
            <button type="button" className="link-btn" onClick={close}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="link-btn" onClick={() => setEditing(true)}>
          {me.hasPassword ? "Change or remove password…" : "Add a password…"}
        </button>
      )}
    </section>
  );
}
