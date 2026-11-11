import { useEffect, useState } from "react";
import { foodEmoji } from "./foodEmoji";
import { useHousehold } from "./household";
import {
  addFridgeItems,
  getFridge,
  clearFridge,
  removeFridgeItem,
  scanFridge,
  type Fridge as FridgeData,
  type FridgeItem,
  type FridgeKind,
  type ScannedItem,
} from "./api";

// "What is in the fridge?" — the household's stock in two kinds. Fresh items
// (keep for less than about a month) are added from the common-items chips, by
// typing, or by scanning photos; each is removed by hand once it's used up.
// Pantry staples (keep a month or longer) are assumed always in the house.
// Both lists go into every planning run.

// Phone photos are several MB; the model reads a fridge just as well at this
// size, and every pixel sent is billed.
const SCAN_MAX_EDGE = 1600;

function downscale(file: File): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, SCAN_MAX_EDGE / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d")?.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("Could not read photo"))),
        "image/jpeg",
        0.85,
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error(`Could not read ${file.name}`));
    };
    img.src = url;
  });
}

function age(addedAt: string): string {
  const days = Math.floor((Date.now() - Date.parse(addedAt)) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

const KIND_EMOJI: Record<FridgeKind, string> = { fresh: "🥬", staple: "🫙" };

function emojiFor(name: string, kind: FridgeKind): string {
  return foodEmoji(name) ?? KIND_EMOJI[kind];
}

// A fresh item this old has probably gone off or been eaten — worth a look.
const STALE_DAYS = 7;

function isStale(addedAt: string): boolean {
  return Date.now() - Date.parse(addedAt) > STALE_DAYS * 86_400_000;
}

function Section({
  kind,
  title,
  blurb,
  items,
  common,
  onAdd,
  onRemove,
  onClear,
}: {
  kind: FridgeKind;
  title: string;
  blurb: string;
  items: FridgeItem[];
  common: string[];
  onAdd: (name: string, kind: FridgeKind) => void;
  onRemove: (item: FridgeItem) => void;
  onClear: (kind: FridgeKind) => void;
}) {
  const [typed, setTyped] = useState("");
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? common : common.slice(0, 18);

  return (
    <section className="fridge-section">
      <div className="fridge-section-head">
        <h2>
          {KIND_EMOJI[kind]} {title}
        </h2>
        {/* Confirmed, since it empties the whole list in one tap. The names
            stay in the common items, so refilling is quick. */}
        <button
          className="btn ghost fridge-clear"
          disabled={items.length === 0}
          onClick={() => {
            if (window.confirm(`Remove all ${items.length} ${title.toLowerCase()}?`)) onClear(kind);
          }}
        >
          Clear
        </button>
      </div>
      <p className="muted">{blurb}</p>

      {items.length === 0 ? (
        <p className="muted fridge-empty">Nothing here yet.</p>
      ) : (
        <ul className="fridge-items">
          {items.map((item) => (
            <li
              key={item.id}
              className={`fridge-item${kind === "fresh" && isStale(item.addedAt) ? " stale" : ""}`}
            >
              <span className="fridge-item-name">
                {emojiFor(item.name, kind)} {item.name}
              </span>
              {kind === "fresh" && (
                <span className="fridge-item-age" title={new Date(item.addedAt).toLocaleString()}>
                  {age(item.addedAt)}
                </span>
              )}
              <button
                className="fridge-remove"
                aria-label={`Remove ${item.name}`}
                title="Remove"
                onClick={() => onRemove(item)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <form
        className="fridge-add"
        onSubmit={(e) => {
          e.preventDefault();
          if (!typed.trim()) return;
          onAdd(typed, kind);
          setTyped("");
        }}
      >
        <input
          type="text"
          placeholder={kind === "fresh" ? "Add an item, e.g. Leftover curry" : "Add a staple, e.g. Coconut milk"}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
        />
        <button className="btn" type="submit" disabled={!typed.trim()}>
          Add
        </button>
      </form>

      {common.length > 0 && (
        <div className="fridge-common">
          {shown.map((name) => (
            <button key={name} className="fridge-pick" onClick={() => onAdd(name, kind)}>
              + {emojiFor(name, kind)} {name}
            </button>
          ))}
          {common.length > shown.length && (
            <button className="fridge-pick more" onClick={() => setShowAll(true)}>
              {common.length - shown.length} more…
            </button>
          )}
        </div>
      )}
    </section>
  );
}

// Review what the scan found before anything is saved: every item starts
// ticked, its kind can be flipped, and only the ticked ones are added.
function ScanReview({
  found,
  onConfirm,
  onClose,
}: {
  found: ScannedItem[];
  onConfirm: (items: ScannedItem[]) => Promise<void>;
  onClose: () => void;
}) {
  const [rows, setRows] = useState(found.map((item) => ({ ...item, keep: true })));
  const [busy, setBusy] = useState(false);
  const kept = rows.filter((r) => r.keep);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="modal">
        <h2>Found in your photos</h2>
        {rows.length === 0 ? (
          <p className="muted">No food items could be made out — try a clearer photo.</p>
        ) : (
          <>
            <p className="muted">Untick anything that's wrong, then add the rest.</p>
            <ul className="scan-rows">
              {rows.map((row, i) => (
                <li key={row.name}>
                  <label>
                    <input
                      type="checkbox"
                      checked={row.keep}
                      onChange={(e) =>
                        setRows(rows.map((r, j) => (j === i ? { ...r, keep: e.target.checked } : r)))
                      }
                    />
                    {emojiFor(row.name, row.kind)} {row.name}
                  </label>
                  <select
                    value={row.kind}
                    onChange={(e) =>
                      setRows(
                        rows.map((r, j) =>
                          j === i ? { ...r, kind: e.target.value as FridgeKind } : r,
                        ),
                      )
                    }
                  >
                    <option value="fresh">Fresh</option>
                    <option value="staple">Pantry staple</option>
                  </select>
                </li>
              ))}
            </ul>
          </>
        )}
        <div className="modal-actions">
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          {rows.length > 0 && (
            <button
              className="btn primary"
              disabled={busy || kept.length === 0}
              onClick={async () => {
                setBusy(true);
                await onConfirm(kept.map(({ name, kind }) => ({ name, kind })));
              }}
            >
              {busy ? "Adding…" : `Add ${kept.length} item${kept.length === 1 ? "" : "s"}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// Photos wait here until "Scan" is pressed: a phone camera hands back one shot
// per pick, so a fridge, its door and the cupboards are several picks.
const MAX_PHOTOS = 8;

type Photo = { blob: Blob; url: string };

function PhotoTray({
  photos,
  scanning,
  onRemove,
  onClear,
  onScan,
}: {
  photos: Photo[];
  scanning: boolean;
  onRemove: (i: number) => void;
  onClear: () => void;
  onScan: () => void;
}) {
  return (
    <div className="photo-tray">
      <div className="photo-thumbs">
        {photos.map((photo, i) => (
          <div key={photo.url} className="photo-thumb">
            <img src={photo.url} alt={`Photo ${i + 1}`} />
            {!scanning && (
              <button aria-label={`Remove photo ${i + 1}`} onClick={() => onRemove(i)}>
                ×
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="photo-tray-actions">
        <span className="muted">
          {photos.length} of {MAX_PHOTOS} photos — add more, or scan them now.
        </span>
        <button className="btn" onClick={onClear} disabled={scanning}>
          Clear
        </button>
        <button className="btn primary" onClick={onScan} disabled={scanning}>
          {scanning ? "Reading photos…" : `🔍 Scan ${photos.length} photo${photos.length === 1 ? "" : "s"}`}
        </button>
      </div>
    </div>
  );
}

export function Fridge() {
  const { go, refreshCounts } = useHousehold();
  const [fridge, setFridge] = useState<FridgeData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [found, setFound] = useState<ScannedItem[] | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);

  useEffect(() => {
    getFridge()
      .then(setFridge)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  async function act(op: () => Promise<FridgeData>) {
    try {
      setError(null);
      setFridge(await op());
      refreshCounts();
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function addPhotos(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    try {
      const room = MAX_PHOTOS - photos.length;
      const picked = Array.from(files).slice(0, room);
      if (files.length > room) setError(`At most ${MAX_PHOTOS} photos per scan.`);
      const blobs = await Promise.all(picked.map(downscale));
      setPhotos((prev) => [
        ...prev,
        ...blobs.map((blob) => ({ blob, url: URL.createObjectURL(blob) })),
      ]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function clearPhotos() {
    photos.forEach((p) => URL.revokeObjectURL(p.url));
    setPhotos([]);
  }

  async function scan() {
    setScanning(true);
    setError(null);
    try {
      setFound(await scanFridge(photos.map((p) => p.blob)));
      clearPhotos();
    } catch (e: unknown) {
      setError(`Scan failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setScanning(false);
    }
  }

  if (fridge === null) {
    return (
      <section className="library">
        {error ? <p className="error">Could not load the fridge: {error}</p> : <p className="muted">Loading…</p>}
      </section>
    );
  }

  const add = (name: string, kind: FridgeKind) => act(() => addFridgeItems([{ name, kind }]));
  const remove = (item: FridgeItem) => act(() => removeFridgeItem(item.id));
  const clear = (kind: FridgeKind) => act(() => clearFridge(kind));

  return (
    <section className="page fridge">
      <header className="page-head">
        <div>
          <h1>What is in the fridge?</h1>
          <p className="muted">The planner uses up what's here first.</p>
        </div>
        <label
          className={`btn${photos.length ? "" : " primary"}${
            scanning || photos.length >= MAX_PHOTOS ? " disabled" : ""
          }`}
        >
          📷 {photos.length ? "Add another photo" : "Photograph the fridge"}
          <input
            type="file"
            accept="image/*"
            multiple
            hidden
            disabled={scanning || photos.length >= MAX_PHOTOS}
            onChange={(e) => {
              void addPhotos(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </header>

      {error && <p className="error">{error}</p>}

      {photos.length > 0 && (
        <PhotoTray
          photos={photos}
          scanning={scanning}
          onRemove={(i) => {
            URL.revokeObjectURL(photos[i].url);
            setPhotos(photos.filter((_, j) => j !== i));
          }}
          onClear={clearPhotos}
          onScan={() => void scan()}
        />
      )}

      <div className="fridge-grid">
        <Section
          kind="fresh"
          title="Fresh items"
          blurb="Keeps for less than a month. Remove each one once it's used up."
          items={fridge.fresh}
          common={fridge.common.fresh}
          onAdd={add}
          onRemove={remove}
          onClear={clear}
        />
        <Section
          kind="staple"
          title="Pantry staples"
          blurb="Keeps for a month or longer — assumed always in the house."
          items={fridge.staples}
          common={fridge.common.staple}
          onAdd={add}
          onRemove={remove}
          onClear={clear}
        />
      </div>

      {fridge.fresh.length > 0 && (
        <div className="next-steps">
          <span className="muted">
            {fridge.fresh.length} fresh {fridge.fresh.length === 1 ? "item" : "items"} to use up
          </span>
          <button className="btn" onClick={() => go("dishes")}>
            Dishes that use them
          </button>
          <button className="btn primary" onClick={() => go("plan")}>
            My week
          </button>
        </div>
      )}

      {found !== null && (
        <ScanReview
          found={found}
          onClose={() => setFound(null)}
          onConfirm={async (items) => {
            await act(() => addFridgeItems(items));
            setFound(null);
          }}
        />
      )}
    </section>
  );
}
