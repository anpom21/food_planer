import { useEffect, useRef, useState } from "react";
import {
  getPrompt,
  previewPrompt,
  savePrompt,
  type PromptConfig,
  type PromptSegment,
} from "./api";

// The planning-prompt editor, opened from the Settings screen. The prompt is
// one household-wide template: anything written as {{variable}} is filled in
// by the backend on every run. Clicking a variable chip inserts it at the
// cursor, and each {{variable}} in the text is coloured as you type. Preview
// renders the draft with every injected value
// highlighted, so it's clear which text came from where.

const VARIABLE = /\{\{\s*(\w+)\s*\}\}/g;

function usedVariables(template: string): string[] {
  return [...new Set([...template.matchAll(VARIABLE)].map((m) => m[1]))];
}

// The template with every {{variable}} wrapped for colouring: known ones in
// the accent, unknown ones flagged. Drawn behind a transparent textarea, so it
// must keep the text exactly as typed — colour and background only, nothing
// that changes a glyph's width.
function highlight(template: string, known: Set<string>): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let pos = 0;
  for (const match of template.matchAll(VARIABLE)) {
    const start = match.index ?? 0;
    if (start > pos) nodes.push(template.slice(pos, start));
    nodes.push(
      <span
        key={start}
        className={known.has(match[1]) ? "tok-var" : "tok-var unknown"}
      >
        {match[0]}
      </span>,
    );
    pos = start + match[0].length;
  }
  nodes.push(template.slice(pos));
  // A trailing newline would collapse in the backdrop; the extra space keeps
  // its last line as tall as the textarea's.
  nodes.push(" ");
  return nodes;
}

export function PromptEditor({ onClose }: { onClose: () => void }) {
  const [config, setConfig] = useState<PromptConfig | null>(null);
  const [draft, setDraft] = useState("");
  const [limit, setLimit] = useState(0);
  const [preview, setPreview] = useState<PromptSegment[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const backdropRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    getPrompt()
      .then((c) => {
        setConfig(c);
        setDraft(c.template);
        setLimit(c.offerLimit);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (config === null) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal wide" onClick={(e) => e.stopPropagation()}>
          {error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}
        </div>
      </div>
    );
  }

  const known = new Set(config.variables.map((v) => v.name));
  const used = usedVariables(draft);
  const unknown = used.filter((name) => !known.has(name));
  const dirty = draft !== config.template || limit !== config.offerLimit;
  const limitValid =
    Number.isInteger(limit) && limit >= 0 && limit <= config.offerLimitCeiling;
  // The default limit is saved as "default" (null), so a later change to the
  // built-in default still reaches this household.
  const limitToSave = limit === config.defaultOfferLimit ? null : limit;

  const edit = (text: string) => {
    setDraft(text);
    setPreview(null);
  };

  // Insert {{name}} at the cursor (or over the selection), then put the cursor
  // just after it so typing carries on naturally.
  const insert = (name: string) => {
    const area = textRef.current;
    const token = `{{${name}}}`;
    const start = area?.selectionStart ?? draft.length;
    const end = area?.selectionEnd ?? draft.length;
    edit(draft.slice(0, start) + token + draft.slice(end));
    requestAnimationFrame(() => {
      area?.focus();
      area?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const showPreview = () =>
    run(async () => setPreview(await previewPrompt(draft, limit)));

  const save = () =>
    run(async () => {
      const saved = await savePrompt(draft, limitToSave);
      setConfig(saved);
      setDraft(saved.template);
      setLimit(saved.offerLimit);
      onClose();
    });

  const reset = () => {
    if (!window.confirm("Replace the prompt with the built-in default?")) return;
    void run(async () => {
      // Only the text resets; the saved offer limit is kept.
      const saved = await savePrompt(
        null,
        config.offerLimit === config.defaultOfferLimit ? null : config.offerLimit,
      );
      setConfig(saved);
      edit(saved.template);
    });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal wide prompt-editor"
        role="dialog"
        aria-label="Planner prompt"
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Planner prompt</h2>
        <p className="review-sub">
          Shared by the whole household. Anything written as{" "}
          <code className="var-token">{"{{variable}}"}</code> is filled in on
          every run. {config.isDefault ? "Currently the built-in default." : "Edited."}
        </p>

        <div className="var-chips">
          {config.variables.map((v) => (
            <button
              key={v.name}
              type="button"
              className={used.includes(v.name) ? "var-chip used" : "var-chip"}
              title={v.description}
              onClick={() => insert(v.name)}
            >
              {`{{${v.name}}}`}
            </button>
          ))}
        </div>

        {preview === null ? (
          <div className="prompt-input">
            <pre ref={backdropRef} className="prompt-backdrop" aria-hidden="true">
              {highlight(draft, known)}
            </pre>
            <textarea
              ref={textRef}
              className="prompt-text"
              spellCheck={false}
              value={draft}
              onChange={(e) => edit(e.target.value)}
              onScroll={(e) => {
                if (backdropRef.current) {
                  backdropRef.current.scrollTop = e.currentTarget.scrollTop;
                }
              }}
            />
          </div>
        ) : (
          <pre className="prompt-preview" aria-label="Rendered prompt">
            {preview.map((seg, i) =>
              seg.variable ? (
                <mark key={i} className="injected" title={`{{${seg.variable}}}`}>
                  {seg.text || "∅"}
                </mark>
              ) : (
                <span key={i}>{seg.text}</span>
              ),
            )}
          </pre>
        )}

        <label className="offer-limit">
          <span>
            Offers in prompt{" "}
            <span className="hint">
              — the top-ranked tilbudsavis offers from your preferred shops,
              ~20 tokens each; 0 lists none (ingredients are still matched to
              offers by name). Default {config.defaultOfferLimit}.
            </span>
          </span>
          <input
            className="input"
            type="number"
            min={0}
            max={config.offerLimitCeiling}
            step={50}
            value={Number.isNaN(limit) ? "" : limit}
            onChange={(e) => {
              setLimit(e.target.valueAsNumber);
              setPreview(null);
            }}
          />
        </label>
        {!limitValid && (
          <p className="error">
            Offers in prompt must be a whole number from 0 to{" "}
            {config.offerLimitCeiling}.
          </p>
        )}

        {unknown.length > 0 && (
          <p className="error">
            Unknown variable{unknown.length > 1 ? "s" : ""}:{" "}
            {unknown.map((n) => `{{${n}}}`).join(", ")}
          </p>
        )}
        {error && <p className="error">{error}</p>}

        <div className="modal-actions">
          <button type="button"
            className="btn ghost prompt-reset"
            onClick={reset}
            disabled={busy || config.isDefault}
          >
            Reset to default
          </button>
          {preview === null ? (
            <button type="button"
              className="btn"
              onClick={() => void showPreview()}
              disabled={busy || unknown.length > 0 || !limitValid}
            >
              Preview
            </button>
          ) : (
            <button type="button" className="btn" onClick={() => setPreview(null)}>
              Edit
            </button>
          )}
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button"
            className="btn primary"
            onClick={() => void save()}
            disabled={
              busy || !dirty || unknown.length > 0 || !draft.trim() || !limitValid
            }
          >
            Save prompt
          </button>
        </div>
      </div>
    </div>
  );
}
