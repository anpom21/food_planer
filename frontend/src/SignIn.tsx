import { useEffect, useState } from "react";
import { checkInvite, signIn, signUp, type InvitePreview, type Me } from "./api";

// The sign-in screen, shown until someone is signed in on this device. A new
// user starts a household of their own — their own fridge, dishes, week and
// list — unless they came through an invite link: then they sign up straight
// into the inviter's household. A password is optional: without one, the
// username alone signs in.

type Mode = "signin" | "signup";

export function SignIn({
  invite,
  onSignedIn,
  onInviteGone,
}: {
  invite: string | null;
  // joined: signed up through the invite, so already in its household.
  onSignedIn: (me: Me, joined: boolean) => void;
  onInviteGone: () => void;
}) {
  const [mode, setMode] = useState<Mode>(invite ? "signup" : "signin");
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = mode === "signup" && password !== "" && password !== repeat;

  useEffect(() => {
    if (!invite) return;
    checkInvite(invite)
      .then(setPreview)
      .catch((e: unknown) => {
        setInviteError(e instanceof Error ? e.message : String(e));
        setMode("signin");
        onInviteGone();
      });
    // Checked once per token; the callback's identity doesn't matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invite]);

  // Signing up joins the invite's household; signing in to an existing user
  // asks afterwards whether to move them (see App's JoinPrompt).
  const joining = mode === "signup" && preview !== null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      const pw = password === "" ? null : password;
      const me =
        mode === "signup"
          ? await signUp(username, pw, joining ? invite : null)
          : await signIn(username, pw);
      onSignedIn(me, joining);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function switchTo(next: Mode) {
    setMode(next);
    setError(null);
    setPassword("");
    setRepeat("");
  }

  return (
    <div className="signin">
      <div className="signin-card">
        <div className="signin-brand">
          <span className="brand-mark">🥕</span>
          <h1>Food Planner</h1>
        </div>

        {preview && (
          <div className="invite-banner">
            <strong>{preview.invitedBy}</strong> invited you to{" "}
            <strong>{preview.householdName}</strong>.
            <span className="muted">
              {mode === "signup"
                ? " Pick a username to join — you'll share the fridge, dishes and shopping list."
                : " Already have a user? Sign in and you'll be asked whether to join."}
            </span>
          </div>
        )}
        {inviteError && <p className="error invite-banner">{inviteError}</p>}

        <div className="segmented signin-modes" role="tablist">
          <button
            role="tab"
            aria-selected={mode === "signin"}
            className={mode === "signin" ? "on" : ""}
            onClick={() => switchTo("signin")}
          >
            Sign in
          </button>
          <button
            role="tab"
            aria-selected={mode === "signup"}
            className={mode === "signup" ? "on" : ""}
            onClick={() => switchTo("signup")}
          >
            New user
          </button>
        </div>

        <form onSubmit={submit} className="signin-form">
          <label className="field">
            <span className="field-label">Username</span>
            <input
              className="input"
              value={username}
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              autoFocus
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>

          <label className="field">
            <span className="field-label">
              Password <span className="field-optional">optional</span>
            </span>
            <input
              className="input"
              type="password"
              value={password}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              placeholder={mode === "signin" ? "Leave empty if you have none" : "At least 8 characters"}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          {mode === "signup" && password !== "" && (
            <label className="field">
              <span className="field-label">Repeat password</span>
              <input
                className="input"
                type="password"
                value={repeat}
                autoComplete="new-password"
                onChange={(e) => setRepeat(e.target.value)}
              />
              {mismatch && repeat !== "" && (
                <span className="field-caption error">The passwords don't match</span>
              )}
            </label>
          )}

          {mode === "signup" && (
            <p className="signin-note">
              {password === ""
                ? "Without a password, anyone who knows your username can open the household."
                : "Your password is stored only as a one-way Argon2 hash: nobody — not even whoever runs this server — can read it back."}
            </p>
          )}

          {error && <p className="error">{error}</p>}

          <button
            className="btn primary large"
            type="submit"
            disabled={busy || username.trim().length < 2 || mismatch}
          >
            {busy
              ? "One moment…"
              : mode === "signup"
                ? joining
                  ? `Join ${preview!.householdName}`
                  : "Create user"
                : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
