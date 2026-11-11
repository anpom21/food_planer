import { useEffect, useState } from "react";
import {
  createInvite,
  getHouseholdInfo,
  inviteUrl,
  revokeInvite,
  type HouseholdInfo,
} from "./api";
import { useHousehold } from "./household";

// Settings → Household: who's in it, and invite links that sign someone up
// straight into it — same fridge, dishes, week and shopping list. A link works
// for a week, for as many people as it's sent to; it can be shown only when
// it's made (the server keeps a digest), so a lost one is revoked and remade.

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export function HouseholdCard() {
  const { me, notify } = useHousehold();
  const [info, setInfo] = useState<HouseholdInfo | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    getHouseholdInfo()
      .then(setInfo)
      .catch((e: unknown) => setError(String(e)));

  useEffect(() => {
    void load();
  }, []);

  async function makeLink() {
    setBusy(true);
    setError(null);
    try {
      const created = await createInvite();
      setLink(inviteUrl(created.token));
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      notify("Invite link copied");
    } catch {
      // Clipboard needs https or localhost; the link is selectable anyway.
      setError("Couldn't copy — select the link and copy it by hand");
    }
  }

  async function share() {
    if (!link) return;
    try {
      await navigator.share({
        title: `Join ${info?.name ?? "our household"} on Food Planner`,
        text: `${me.username} invited you to plan meals together.`,
        url: link,
      });
    } catch {
      // Cancelled by the person: nothing to do.
    }
  }

  async function revoke(id: string) {
    try {
      await revokeInvite(id);
      setLink(null);
      await load();
      notify("Invite link revoked");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const canShare = typeof navigator.share === "function";

  return (
    <section className="settings-card household-card">
      <label>{info?.name ?? "Household"}</label>
      <p className="muted">
        Everyone here shares the fridge, dishes, My week, the shopping list and
        these settings.
      </p>
      {info && (
        <ul className="member-list">
          {info.members.map((m) => (
            <li key={m.id} className="member">
              <span className="member-avatar" aria-hidden="true">
                {m.username.slice(0, 1).toUpperCase()}
              </span>
              {m.username}
              {m.id === me.id && <span className="muted"> (you)</span>}
            </li>
          ))}
        </ul>
      )}

      {link ? (
        <div className="invite-link">
          <span className="field-label">Send this link to whoever should join</span>
          <input
            className="input"
            readOnly
            value={link}
            onFocus={(e) => e.currentTarget.select()}
          />
          <div className="account-actions">
            {canShare && (
              <button type="button" className="btn primary" onClick={() => void share()}>
                Share…
              </button>
            )}
            <button
              type="button"
              className={canShare ? "btn" : "btn primary"}
              onClick={() => void copy()}
            >
              Copy link
            </button>
            <button type="button" className="link-btn" onClick={() => setLink(null)}>
              Done
            </button>
          </div>
          <p className="muted account-note">
            Works for a week, for anyone you send it to. Opening it, they pick a
            username and land in this household.
          </p>
        </div>
      ) : (
        <button type="button" className="btn" disabled={busy} onClick={() => void makeLink()}>
          {busy ? "Making a link…" : "＋ Invite someone"}
        </button>
      )}

      {info && info.invites.length > 0 && (
        <ul className="invite-list">
          {info.invites.map((i) => (
            <li key={i.id}>
              <span className="muted">
                Link by {i.createdBy} · until {shortDate(i.expiresAt)}
              </span>
              <button type="button" className="link-btn" onClick={() => void revoke(i.id)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
