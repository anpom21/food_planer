// Each chain's brand colour, for the little square that marks its offers on
// the shopping list. Keyed by the settings slug (see shops.py: æ/ø/å are
// stripped, so Føtex is "ftex").
const BRAND: Record<string, string> = {
  netto: "#ffd200", // yellow
  "rema-1000": "#1b3f94", // blue
  ftex: "#0b2a5b", // navy
  bilka: "#00a0e1", // light blue
  lidl: "#0050aa", // blue
  aldi: "#00005f", // dark blue
  "coop-365": "#00a651", // green
  superbrugsen: "#e2001a", // red
  irma: "#2b5cab", // blue
  meny: "#c8102e", // red
};

const UNKNOWN = "#a39a90";

export function shopColor(slug: string | null | undefined): string {
  return (slug && BRAND[slug]) || UNKNOWN;
}

// A display name for a shop whose dealer name differs from the chain's.
const NAMES: Record<string, string> = { "coop-365": "Coop 365", "rema-1000": "Rema 1000", ftex: "Føtex" };

export function shopName(slug: string | null | undefined, dealerName: string): string {
  return (slug && NAMES[slug]) || dealerName;
}
