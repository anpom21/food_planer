import { useEffect, useMemo, useState } from "react";
import {
  getShopOffers,
  listShops,
  type Offer,
  type Profile,
  type Shop,
  type ShopOffers,
} from "./api";
import { ShopMark } from "./SettingsScreen";

// The tilbudsavis: this week's offers for one chain, straight from
// eTilbudsavis (Tjek). The Profile's preferred shops lead the picker and the
// first of them is opened by default; any other chain is one tap away. The
// backend caches each chain's offers for a day, so browsing is cheap.

const kr = new Intl.NumberFormat("da-DK", {
  style: "currency",
  currency: "DKK",
});

function dateLabel(iso: string | null): string {
  if (!iso) return "";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("da-DK", {
    day: "numeric",
    month: "short",
  });
}

function matches(offer: Offer, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return `${offer.item_name} ${offer.description ?? ""}`.toLowerCase().includes(q);
}

type Sort = "paper" | "discount" | "price";

function sortOffers(offers: Offer[], sort: Sort): Offer[] {
  if (sort === "paper") return offers;
  const sorted = [...offers];
  if (sort === "discount") {
    sorted.sort((a, b) => (b.discount_percent ?? -1) - (a.discount_percent ?? -1));
  } else {
    sorted.sort((a, b) => (a.price ?? Infinity) - (b.price ?? Infinity));
  }
  return sorted;
}

function OfferCard({ offer }: { offer: Offer }) {
  return (
    <article className="offer-card">
      {offer.image_url ? (
        <img className="offer-img" src={offer.image_url} alt="" loading="lazy" />
      ) : (
        <div className="offer-img" aria-hidden="true" />
      )}
      <div className="offer-body">
        <h3 className="offer-name">{offer.item_name}</h3>
        {offer.description && <p className="offer-desc">{offer.description}</p>}
        <div className="offer-price">
          {offer.price !== null && <strong>{kr.format(offer.price)}</strong>}
          {offer.pre_price !== null && <s>{kr.format(offer.pre_price)}</s>}
          {offer.discount_percent !== null && (
            <span className="chip discount">−{Math.round(offer.discount_percent)}%</span>
          )}
        </div>
        <p className="offer-meta">
          {offer.unit_size && <span>{offer.unit_size}</span>}
          {offer.valid_from && offer.valid_to && (
            <span>
              {dateLabel(offer.valid_from)} – {dateLabel(offer.valid_to)}
            </span>
          )}
        </p>
      </div>
    </article>
  );
}

export function Offers({ profile }: { profile: Profile }) {
  const [catalog, setCatalog] = useState<Shop[] | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [result, setResult] = useState<ShopOffers | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("paper");

  const preferred = new Set(profile.settings.shops);

  useEffect(() => {
    listShops()
      .then((shops) => {
        setCatalog(shops);
        const first = shops.find((s) => preferred.has(s.slug)) ?? shops[0];
        setSlug(first?.slug ?? null);
      })
      .catch((e: unknown) => setError(String(e)));
    // Seed once per Profile (the screen is keyed by profile id).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!slug) return;
    let stale = false;
    setLoading(true);
    setError(null);
    getShopOffers(slug)
      .then((r) => !stale && setResult(r))
      .catch((e: unknown) => !stale && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
  }, [slug]);

  const visible = useMemo(
    () => sortOffers((result?.offers ?? []).filter((o) => matches(o, query)), sort),
    [result, query, sort],
  );

  // Preferred chains first, then the rest, each group in catalog order.
  const ordered = [
    ...(catalog ?? []).filter((s) => preferred.has(s.slug)),
    ...(catalog ?? []).filter((s) => !preferred.has(s.slug)),
  ];

  return (
    <section className="offers">
      <header className="toolbar">
        <div>
          <h1>Tilbudsavis</h1>
          <p className="muted">
            This week's offers from eTilbudsavis. Your preferred shops come first.
          </p>
        </div>
      </header>

      <div className="pill-grid">
        {ordered.map((shop) => (
          <button
            type="button"
            key={shop.slug}
            className={shop.slug === slug ? "shop-pill selected" : "shop-pill"}
            aria-pressed={shop.slug === slug}
            onClick={() => setSlug(shop.slug)}
          >
            <ShopMark shop={shop} />
            {shop.name}
            {preferred.has(shop.slug) && <span aria-label="preferred">★</span>}
          </button>
        ))}
      </div>

      <div className="offers-bar">
        <input
          className="input"
          type="search"
          placeholder="Search offers, e.g. kylling"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="input"
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          aria-label="Sort offers"
        >
          <option value="paper">As in the paper</option>
          <option value="discount">Biggest discount</option>
          <option value="price">Lowest price</option>
        </select>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Fetching the tilbudsavis…</p>}

      {!loading && !error && result && result.shop.slug === slug && (
        result.dealer === null ? (
          <p className="muted">
            eTilbudsavis has no offers for {result.shop.name}.
          </p>
        ) : (
          <>
            <p className="muted">
              {visible.length} of {result.offers.length} offers from{" "}
              {result.dealer.name}
            </p>
            <div className="offer-grid">
              {visible.map((offer) => (
                <OfferCard key={offer.id} offer={offer} />
              ))}
            </div>
          </>
        )
      )}
    </section>
  );
}
