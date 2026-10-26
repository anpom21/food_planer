import type { Reminder } from "./api";

// Sending the shopping list to the iPhone's Påmindelser (Reminders) app.
//
// A web page can't write to Reminders, but an iOS Shortcut can, and a page can
// start one with a shortcuts:// link that carries input. So the app hands the
// list, as JSON, to a shortcut installed once from an iCloud link; the shortcut
// adds one reminder per item — the ingredient as the title, "500 g · Chili con
// carne" as the note under it.

// The shortcut's name must match the shared shortcut's name exactly.
export const SHORTCUT_NAME = "Indkøbsliste til Påmindelser";
const SHORTCUT_INSTALL_URL =
  "https://www.icloud.com/shortcuts/8ab374ba19ab4a14a10a8a5bf6eddc42";

const READY_KEY = "foodPlanner.remindersShortcutReady";

// Whether this phone has the shortcut, as far as we know — remembered per
// device once the setup guide has been followed. Storage can be blocked
// (private browsing); then the guide simply shows again.
export function shortcutReady(): boolean {
  try {
    return localStorage.getItem(READY_KEY) === "yes";
  } catch {
    return false;
  }
}

export function markShortcutReady(): void {
  try {
    localStorage.setItem(READY_KEY, "yes");
  } catch {
    // Not remembered; the guide shows again next time. Nothing else breaks.
  }
}

// Open Shortcuts and run the shortcut with the reminders as its input.
export function runShortcut(reminders: Reminder[]): void {
  const input = JSON.stringify({ items: reminders });
  window.location.href =
    `shortcuts://run-shortcut?name=${encodeURIComponent(SHORTCUT_NAME)}` +
    `&input=text&text=${encodeURIComponent(input)}`;
}

// The one-time setup: install the household's shortcut from iCloud, then
// confirm so this phone remembers it and runs it from then on.
export function RemindersSetup({ onDone }: { onDone: () => void }) {
  return (
    <div className="reminders-setup">
      <p>
        Send the shopping list to <strong>Påmindelser</strong> — one reminder per
        item, with the amount and the dishes it's for underneath. It takes a small
        shortcut on the iPhone, installed once:
      </p>
      <ol className="setup-steps">
        <li>
          Tap <strong>Install shortcut</strong> and add{" "}
          <code>{SHORTCUT_NAME}</code> in the <strong>Genveje</strong> app.
        </li>
        <li>Come back here and tap <strong>I've installed it</strong>.</li>
        <li>The first time it runs, allow it to add to Påmindelser.</li>
      </ol>
      <p className="muted">
        After that, the Påmindelser button sends the list in one tap — or just the
        rows you've ticked.
      </p>
      <div className="modal-actions">
        <a className="btn" href={SHORTCUT_INSTALL_URL} target="_blank" rel="noreferrer">
          Install shortcut
        </a>
        <button className="btn primary" onClick={onDone}>
          I've installed it — send the list
        </button>
      </div>
    </div>
  );
}
