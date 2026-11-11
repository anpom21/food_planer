"""Browsing a chain's tilbudsavis: ``GET /api/shops/{slug}/offers``.

Driven through the fake Tjek client with payloads shaped like the real API,
including the awkward cases: ``pre_price: null``, empty ``category_ids``, and a
chain Tjek doesn't carry.

- offers come back normalised into the spec's ``Offer`` shape;
- ``discount_percent`` is only set when a markdown is advertised;
- validity dates are Danish local dates, not the UTC ones Tjek sends;
- a chain resolves to its dealer by name, aliases included ("Coop 365");
- a chain Tjek doesn't carry answers with ``dealer: null`` and no offers;
- dealers and offers are cached, so browsing again doesn't call Tjek again;
- an unknown slug is a 404, a Tjek failure a 502.
"""

from __future__ import annotations

from typing import Any


def _offer(offer_id: str, heading: str, price: float, pre_price: float | None) -> dict[str, Any]:
    return {
        "id": offer_id,
        "heading": heading,
        "description": "8 stk. Str. M/L.\nPr. stk. 2,00",
        "pricing": {"price": price, "pre_price": pre_price, "currency": "DKK"},
        "quantity": {
            "size": {"from": 8, "to": 8},
            "unit": {"symbol": "pcs", "si": {"symbol": "pcs", "factor": 1}},
        },
        "run_from": "2026-10-16T22:00:00+0000",
        "run_till": "2026-10-23T21:59:59+0000",
        "category_ids": [],
        "images": {"view": f"https://img.example/{offer_id}.webp"},
    }


def _stock(fake_tjek) -> None:
    fake_tjek.dealers = [
        {"id": "n1", "name": "Netto"},
        {"id": "m1", "name": "MENY Vin"},
        {"id": "m2", "name": "MENY"},
        {"id": "c3", "name": "365discount"},
    ]
    fake_tjek.offers = {
        "n1": [
            _offer("o1", "Frilandsæg", 16, None),
            _offer("o2", "Tranebær", 13.37, 26.75),
        ],
        "c3": [_offer("o3", "Kyllingebryst", 45, 60)],
    }


def test_offers_come_back_normalised(client, fake_tjek) -> None:
    _stock(fake_tjek)

    body = client.get("/api/shops/netto/offers").json()

    assert body["shop"] == {"slug": "netto", "name": "Netto"}
    assert body["dealer"] == {"id": "n1", "name": "Netto"}
    assert body["fetchedAt"]
    eggs, berries = body["offers"]
    assert eggs["item_name"] == "Frilandsæg"
    assert eggs["source"] == "tjek_api"
    assert eggs["shop"] == "Netto"
    assert eggs["price"] == 16
    assert eggs["pre_price"] is None
    assert eggs["discount_percent"] is None  # a flat weekly price
    assert eggs["unit_size"] == "8 pcs"
    assert eggs["category"] is None
    assert eggs["image_url"] == "https://img.example/o1.webp"
    assert berries["discount_percent"] == 50.0


def test_validity_is_a_danish_local_date(client, fake_tjek) -> None:
    _stock(fake_tjek)

    eggs = client.get("/api/shops/netto/offers").json()["offers"][0]

    # 22:00 UTC on the 16th is midnight on the 17th in Copenhagen.
    assert eggs["valid_from"] == "2026-10-17"
    assert eggs["valid_to"] == "2026-10-23"


def test_chain_resolves_by_exact_name_then_alias(client, fake_tjek) -> None:
    _stock(fake_tjek)

    assert client.get("/api/shops/meny/offers").json()["dealer"]["id"] == "m2"
    coop = client.get("/api/shops/coop-365/offers").json()
    assert coop["dealer"]["name"] == "365discount"
    assert coop["offers"][0]["item_name"] == "Kyllingebryst"


def test_chain_tjek_does_not_carry_has_no_offers(client, fake_tjek) -> None:
    _stock(fake_tjek)

    resp = client.get("/api/shops/irma/offers")

    assert resp.status_code == 200
    assert resp.json()["dealer"] is None
    assert resp.json()["offers"] == []


def test_dealers_and_offers_are_cached(client, fake_tjek) -> None:
    _stock(fake_tjek)

    client.get("/api/shops/netto/offers")
    client.get("/api/shops/netto/offers")
    client.get("/api/shops/meny/offers")

    assert fake_tjek.dealer_calls == 1
    assert fake_tjek.offer_calls == 2  # once each for Netto and MENY


def test_unknown_slug_is_404(client) -> None:
    assert client.get("/api/shops/nowhere/offers").status_code == 404


def test_tjek_failure_is_502(client, fake_tjek) -> None:
    fake_tjek.fail = True

    resp = client.get("/api/shops/netto/offers")

    assert resp.status_code == 502
    assert "Netto" in resp.json()["detail"]


def test_concurrent_cold_fetches_list_dealers_once() -> None:
    import asyncio

    from food_planer.clients import FakeTjekClient
    from food_planer.discounts import OfferCatalog

    fake = FakeTjekClient(
        dealers=[{"id": "n1", "name": "Netto"}, {"id": "r1", "name": "REMA 1000"}],
        offers={"n1": [], "r1": []},
    )
    catalog = OfferCatalog()

    asyncio.run(
        catalog.offers_for_shops(["Netto", "Rema 1000", "Netto", "Aldi"], fake)
    )

    assert fake.dealer_calls == 1
    assert fake.offer_calls == 2  # Netto once, despite being asked twice
