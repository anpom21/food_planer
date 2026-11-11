import { useEffect, useState } from "react";
import {
  getClaudeStatus,
  getModelSettings,
  saveModelSettings,
  type ClaudeStatus,
  type ModelProvider,
  type ModelSettings,
} from "./api";

// Settings → Model: which LLM plans the week, reads fridge photos and checks
// offer matches. Either OpenAI with an API key, or Claude through the Claude
// Code install on the machine running the app, which uses its Pro/Max
// subscription login. Saved on its own, apart from the planning settings.

const PROVIDERS: { provider: ModelProvider; label: string; hint: string }[] = [
  { provider: "openai", label: "OpenAI", hint: "API key, billed per call" },
  { provider: "claude-code", label: "Claude", hint: "your Pro/Max plan via Claude Code" },
];

const CLAUDE_MODELS = [
  { id: "claude-opus-5-5", label: "Opus 5.5 — best plans" },
  { id: "claude-sonnet-5-5", label: "Sonnet 5.5 — faster" },
  { id: "claude-haiku-5-5", label: "Haiku 5.5 — fastest, lightest on usage" },
];

function ClaudeLogin({ tokenSet, refresh }: { tokenSet: boolean; refresh: number }) {
  const [status, setStatus] = useState<ClaudeStatus | null>(null);
  const [checking, setChecking] = useState(false);

  const check = () => {
    setChecking(true);
    getClaudeStatus()
      .then(setStatus)
      .catch((e: unknown) => setStatus({ installed: true, loggedIn: false, error: String(e) }))
      .finally(() => setChecking(false));
  };
  useEffect(check, [tokenSet, refresh]);

  if (status === null) return <p className="muted">Checking Claude Code…</p>;
  return (
    <div className="claude-login">
      {status.loggedIn ? (
        <p className="ok-note">
          ✓{" "}
          {status.authMethod === "token"
            ? "Using the saved Claude Code token"
            : `Signed in to Claude Code${status.email ? ` as ${status.email}` : ""}${
                status.subscriptionType ? ` (${status.subscriptionType} plan)` : ""
              }`}
        </p>
      ) : status.needsToken ? (
        <p className="error">
          Claude Code on this server is signed in to its owner's plan, which only
          their household may use. Run <code>claude setup-token</code> with your own Pro/Max
          plan and paste the token below.
        </p>
      ) : !status.installed ? (
        <p className="error">
          Claude Code isn't installed on the machine running the app. Install it,
          then run <code>claude auth login</code> there.
        </p>
      ) : (
        <p className="error">
          Claude Code isn't signed in. On the machine running the app, run{" "}
          <code>claude auth login</code>, or paste a token below.
        </p>
      )}
      <button type="button" className="btn" onClick={check} disabled={checking}>
        {checking ? "Checking…" : "Check again"}
      </button>
    </div>
  );
}

export function ModelSettingsCard() {
  const [stored, setStored] = useState<ModelSettings | null>(null);
  const [provider, setProvider] = useState<ModelProvider>("openai");
  const [openaiModel, setOpenaiModel] = useState("");
  const [claudeModel, setClaudeModel] = useState("");
  // Secrets typed here; empty means "leave the saved one alone".
  const [openaiKey, setOpenaiKey] = useState("");
  const [claudeToken, setClaudeToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusRefresh, setStatusRefresh] = useState(0);

  const load = (m: ModelSettings) => {
    setStored(m);
    setProvider(m.provider);
    setOpenaiModel(m.openaiModel ?? "");
    setClaudeModel(m.claudeModel ?? m.defaultClaudeModel);
    setOpenaiKey("");
    setClaudeToken("");
  };

  useEffect(() => {
    getModelSettings()
      .then(load)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const save = async (secrets: { openaiApiKey?: string; claudeToken?: string } = {}) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await saveModelSettings({
        provider,
        openaiModel: openaiModel.trim() || null,
        claudeModel: claudeModel || null,
        openaiApiKey: openaiKey.trim() || null,
        claudeToken: claudeToken.trim() || null,
        ...secrets,
      });
      load(updated);
      setSaved(true);
      setStatusRefresh((n) => n + 1);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (stored === null) {
    return (
      <section className="settings-card">
        <label>Model</label>
        {error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}
      </section>
    );
  }

  const edit = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setSaved(false);
  };

  return (
    <form
      className="settings model-settings"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <section className="settings-card">
        <label>
          Model <span className="hint">— plans the week, reads fridge photos</span>
        </label>
        <div className="mode-pills" role="radiogroup" aria-label="Model provider">
          {PROVIDERS.map((p) => (
            <button
              key={p.provider}
              type="button"
              role="radio"
              aria-checked={provider === p.provider}
              className={`mode-pill${provider === p.provider ? " on" : ""}`}
              onClick={() => edit(setProvider)(p.provider)}
            >
              <strong>{p.label}</strong>
              <span>{p.hint}</span>
            </button>
          ))}
        </div>

        {stored.usesOwnCredentialsOnly && (
          <p className="muted own-credentials-note">
            Use your own OpenAI key or Claude token — the server's own are only
            for its owner's household.
          </p>
        )}

        {provider === "openai" ? (
          <div className="model-fields">
            <div className="field">
              <label htmlFor="openai-key">API key</label>
              <input
                id="openai-key"
                type="password"
                autoComplete="off"
                placeholder={
                  stored.openaiKeySet
                    ? `Saved key …${stored.openaiKeyHint} — type to replace`
                    : stored.openaiKeyFromEnv
                      ? "Using OPENAI_API_KEY from .env — type to override"
                      : "sk-…"
                }
                value={openaiKey}
                onChange={(e) => edit(setOpenaiKey)(e.target.value)}
              />
              {stored.openaiKeySet && (
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => void save({ openaiApiKey: "" })}
                >
                  Remove saved key
                </button>
              )}
            </div>
            <div className="field">
              <label htmlFor="openai-model">Model</label>
              <input
                id="openai-model"
                type="text"
                placeholder={stored.defaultOpenaiModel}
                value={openaiModel}
                onChange={(e) => edit(setOpenaiModel)(e.target.value)}
              />
            </div>
          </div>
        ) : (
          <div className="model-fields">
            <ClaudeLogin tokenSet={stored.claudeTokenSet} refresh={statusRefresh} />
            <div className="field">
              <label htmlFor="claude-model">Model</label>
              <select
                id="claude-model"
                value={claudeModel}
                onChange={(e) => edit(setClaudeModel)(e.target.value)}
              >
                {CLAUDE_MODELS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="claude-token">
                Token <span className="hint">— optional, from <code>claude setup-token</code></span>
              </label>
              <input
                id="claude-token"
                type="password"
                autoComplete="off"
                placeholder={
                  stored.claudeTokenSet
                    ? "Saved token — type to replace"
                    : "Only needed when Claude Code isn't signed in here"
                }
                value={claudeToken}
                onChange={(e) => edit(setClaudeToken)(e.target.value)}
              />
              {stored.claudeTokenSet && (
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => void save({ claudeToken: "" })}
                >
                  Remove saved token
                </button>
              )}
            </div>
          </div>
        )}
      </section>
      <div className="settings-actions">
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save model"}
        </button>
        {saved && <span className="saved-note">Saved ✓</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </form>
  );
}
