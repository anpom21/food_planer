"""Offer matches that aren't 1:1 are checked by the model before they stick.

- a name match is graded: ``exact`` when some product in the heading *is* the
  ingredient (whole words, a brand or two beside it), ``review`` otherwise —
  compounds, words only after "med"/"af", long headings;
- an exact match is attached straight away; nothing is reviewed;
- an ingredient we already have (fridge or pantry) gets no offer by name;
- review matches go to one review call; only what the model confirms is
  attached (``matchedBy: "review"``), and the same pair is asked once;
- a failed or refused review attaches none of them;
- in the planning prompt, a recipe's uncertain offers are marked "check offer"
  with the product's name, so the planner judges them itself.
"""

from __future__ import annotations

from typing import Any

import pytest

from food_planer.discounts import match_grade


@pytest.mark.parametrize(
    ("ingredient", "heading", "grade"),
    [
        ("agurk", "Agurk", "exact"),
        ("smør", "Lurpak smør eller smørbar", "exact"),
        ("hakket oksekød", "Netto hakket oksekød 4-7%", "exact"),
        ("cheddar", "Salling Princip Cheddar eller danablu", "exact"),  # a variant pair
        ("mælk", "Arla laktosefri mælk", "exact"),
        ("salat", "K-Salat bearnaisesauce", "review"),  # a hyphenated compound
        ("æg", "Dava danske frilandsæg", "review"),  # a compound's tail
        ("løg", "Samsø rødløg", "review"),
        ("okseinderlår", "Roastbeef af okseinderlår", "review"),  # after "af"
        ("burgerboller", "Salling Princip briocheburgerboller", "review"),
        ("tun", "REMA 1000 Tun-, hønse- eller skinkesalat", "review"),
        # Three or more products is a mixed promotion: cold cuts, not raw chicken.
        ("kyllingebryst", "XXL kyllinge-sandwichskiver, hamburgerryg, kyllingebryst eller rullepølse", "review"),
    ],
)
def test_match_grade(ingredient: str, heading: str, grade: str) -> None:
    assert match_grade(ingredient, {"item_name": heading}) == grade


def _raw_offer(offer_id: str, heading: str) -> dict[str, Any]:
    return {
        "id": offer_id,
        "heading": heading,
        "description": None,
        "pricing": {"price": 20, "pre_price": None, "currency": "DKK"},
        "quantity": None,
        "run_from": "2026-10-16T22:00:00+0000",
        "run_till": "2026-10-23T21:59:59+0000",
        "category_ids": [],
        "images": {},
        "catalog_label": "Netto Uge 43",
    }


def _suggestion(title: str, *ingredients: str) -> dict[str, Any]:
    return {
        "title": title,
        "description": "Dinner.",
        "ingredients": [{"name": n, "quantity": "1"} for n in ingredients],
        "estimatedCost": 60.0,
        "prepTimeMinutes": 30,
        "sourceDish": None,
        "sourceRecipe": None,
        "discounts": [],
    }


def _plan(client, fake_openai, fake_tjek, offers, *suggestions) -> dict[str, Any]:
    fake_tjek.dealers = [{"id": "n1", "name": "Netto"}]
    fake_tjek.offers = {"n1": offers}
    fake_openai.canned = {"days": [{"day": 1, "suggestions": list(suggestions)}]}
    client.put(
        "/api/settings",
        json={"daysToPlan": 1, "suggestionsPerDay": len(suggestions), "shops": ["netto"]},
    )
    return client.post("/api/planning-runs", json={}).json()


def _offers_by_ingredient(suggestion: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {
        d["matchedIngredient"]: (d["productName"], d["matchedBy"])
        for d in suggestion["discounts"]
    }


def test_exact_matches_attach_without_a_review(client, fake_openai, fake_tjek) -> None:
    run = _plan(
        client, fake_openai, fake_tjek, [_raw_offer("t-1", "Agurk")],
        _suggestion("Salat", "agurk"),
    )

    assert _offers_by_ingredient(run["days"][0]["suggestions"][0]) == {
        "agurk": ("Agurk", "name")
    }
    assert fake_openai.reviews == []


def test_the_model_confirms_or_rejects_uncertain_matches(
    client, fake_openai, fake_tjek
) -> None:
    fake_openai.review_output = {"verdicts": [{"id": "m1", "match": True}]}
    offers = [_raw_offer("t-1", "Dava danske frilandsæg"), _raw_offer("t-2", "K-Salat bearnaisesauce")]

    run = _plan(
        client, fake_openai, fake_tjek, offers,
        _suggestion("Omelet", "æg", "salat"),
        _suggestion("Æggekage", "æg"),  # the same pair again: asked once
    )

    (prompt,) = fake_openai.reviews
    assert "[m1] ingredient: æg — offer: Dava danske frilandsæg at Netto" in prompt
    assert "[m2] ingredient: salat — offer: K-Salat bearnaisesauce at Netto" in prompt
    assert "[m3]" not in prompt
    first, second = run["days"][0]["suggestions"]
    assert _offers_by_ingredient(first) == {"æg": ("Dava danske frilandsæg", "review")}
    assert _offers_by_ingredient(second) == {"æg": ("Dava danske frilandsæg", "review")}


@pytest.mark.parametrize("failure", ["raise", "refuse"])
def test_a_failed_review_attaches_nothing(client, fake_openai, fake_tjek, failure) -> None:
    async def broken(*, prompt: str, schema: dict[str, Any]):
        if failure == "raise":
            raise TimeoutError("Request timed out.")
        from food_planer.clients import LLMResult

        return LLMResult(status="refused")

    fake_openai.review_matches = broken

    run = _plan(
        client, fake_openai, fake_tjek, [_raw_offer("t-1", "Dava danske frilandsæg")],
        _suggestion("Omelet", "æg"),
    )

    assert run["status"] == "success"
    assert run["days"][0]["suggestions"][0]["discounts"] == []


def test_ingredients_we_have_get_no_offer_by_name(client, fake_openai, fake_tjek) -> None:
    client.post(
        "/api/fridge/items",
        json=[{"name": "Cucumber", "kind": "fresh"}, {"name": "Onions", "kind": "staple"}],
    )

    run = _plan(
        client, fake_openai, fake_tjek,
        [_raw_offer("t-1", "Agurk"), _raw_offer("t-2", "Løg"), _raw_offer("t-3", "Spidskål")],
        _suggestion("Salat", "agurk", "løg", "spidskål"),
    )

    suggestion = run["days"][0]["suggestions"][0]
    assert _offers_by_ingredient(suggestion) == {"spidskål": ("Spidskål", "name")}
    assert [i["have"] for i in suggestion["ingredients"]] == ["fresh", "staple", None]


def test_a_bracketed_ref_from_the_model_is_still_understood(
    client, fake_openai, fake_tjek
) -> None:
    suggestion = _suggestion("Salat", "agurk")
    suggestion["discounts"] = [{"offerId": "[o1]", "matchedIngredient": "agurk"}]

    run = _plan(client, fake_openai, fake_tjek, [_raw_offer("t-1", "Agurk")], suggestion)

    assert _offers_by_ingredient(run["days"][0]["suggestions"][0]) == {
        "agurk": ("Agurk", "model")
    }


# --- Offers carry their shop's settings slug -------------------------------
# A dish only shows offers from shops selected in settings (filtered in the
# frontend), so every stored offer names its shop the way settings do.


@pytest.mark.parametrize(
    ("dealer", "slug"),
    [
        ("Netto", "netto"),
        ("365discount", "coop-365"),  # Coop 365's Tjek dealer has another name
        ("REMA 1000", "rema-1000"),
        ("Føtex", "ftex"),
        ("Bilka ToGo", "bilka"),
        ("Kvickly", None),  # not a chain the app knows
        (None, None),
    ],
)
def test_shop_slug_maps_a_dealer_to_its_settings_slug(dealer, slug) -> None:
    from food_planer.discounts import shop_slug

    assert shop_slug(dealer) == slug


def test_offers_on_dishes_carry_their_shop_slug(client, fake_openai, fake_tjek) -> None:
    run = _plan(
        client, fake_openai, fake_tjek, [_raw_offer("t-1", "Agurk")],
        _suggestion("Salat", "agurk"),
    )

    (discount,) = run["days"][0]["suggestions"][0]["discounts"]
    assert discount["shop"] == "Netto"
    assert discount["shopSlug"] == "netto"
    assert client.get(f"/api/planning-runs/{run['id']}").json()["days"][0]["suggestions"][0][
        "discounts"
    ][0]["shopSlug"] == "netto"


def test_an_old_run_gets_shop_slugs_when_read(make_client, data_dir) -> None:
    import json

    run = {
        "id": "old", "createdAt": "2026-10-01T18:00:00+00:00",
        "status": "success", "dayCount": 1, "dishIds": [],
        "fridgeSnippet": "", "requestedDays": None, "requestedSuggestionsPerDay": None,
        "offerCount": 1, "offersUnavailable": [], "error": None,
        "days": [{"day": 1, "suggestions": [{
            "title": "Salat", "description": "", "ingredients": [], "estimatedCost": 40,
            "prepTimeMinutes": 10, "sourceDish": None,
            # Stored before offers carried a shopSlug.
            "discounts": [{"offerId": "x", "productName": "Agurk", "shop": "365discount"}],
        }]}],
    }
    data_dir.mkdir(parents=True)
    (data_dir / "planning_runs.json").write_text(json.dumps([run]), "utf-8")

    body = make_client(data_dir).get("/api/planning-runs/old").json()

    assert body["days"][0]["suggestions"][0]["discounts"][0]["shopSlug"] == "coop-365"
