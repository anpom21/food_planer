"""Offers steering a PlanningRun: the DiscountData pipeline end to end.

Driven through ``POST /api/planning-runs`` with the fake Tjek and OpenAI
clients (spec.md → "LLM contract", "What gets tested"):

- the preferred shops' offers reach the prompt, each with a short [id];
- non-food is denylisted out — by heading, and by a non-food tilbudsavis;
- offers matching a Dish ingredient rank ahead of merely-discounted ones;
- the ~100 cap holds;
- no preferred shops, or nothing relevant, plans silently without offers;
- a Tjek failure plans anyway and names the chain that was missed;
- the model cites offers by [id]; the run stores the full offer (image,
  price, dates) in their place, so an archived run stays complete;
- an id the model made up is dropped, a repeated one kept once;
- an ingredient the model didn't cite is still tied to an offer by name;
- the preferred shops take turns filling the capped list;
- every run writes a debug trace (settings, prompt, raw output, result).
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _raw_offer(
    offer_id: str,
    heading: str,
    price: float = 20,
    pre_price: float | None = None,
    catalog: str = "Netto Uge 43",
) -> dict[str, Any]:
    return {
        "id": offer_id,
        "heading": heading,
        "description": None,
        "pricing": {"price": price, "pre_price": pre_price, "currency": "DKK"},
        "quantity": {"size": {"from": 400, "to": 400}, "unit": {"symbol": "g"}},
        "run_from": "2026-10-16T22:00:00+0000",
        "run_till": "2026-10-23T21:59:59+0000",
        "category_ids": [],
        "images": {"view": f"https://img.example/{offer_id}.webp"},
        "catalog_label": catalog,
    }


def _suggestion(title: str, discounts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": title,
        "description": "Dinner.",
        "ingredients": [{"name": "hakket oksekød", "quantity": "400 g"}],
        "estimatedCost": 60.0,
        "prepTimeMinutes": 30,
        "sourceDish": None,
        "discounts": discounts,
    }


def _settings(client: TestClient, shops: list[str], days: int = 1, per_day: int = 1) -> None:
    client.put(
        "/api/settings",
        json={"daysToPlan": days, "suggestionsPerDay": per_day, "shops": shops},
    )


def _plan(client: TestClient) -> dict[str, Any]:
    resp = client.post("/api/planning-runs", json={})
    assert resp.status_code == 200
    return resp.json()


def _stock_netto(fake_tjek, offers: list[dict[str, Any]]) -> None:
    fake_tjek.dealers = [{"id": "n1", "name": "Netto"}, {"id": "r1", "name": "REMA 1000"}]
    fake_tjek.offers = {"n1": offers, "r1": [_raw_offer("r-1", "Rema kaffe")]}


def test_preferred_shop_offers_reach_the_prompt_with_ids(
    client, fake_openai, fake_tjek
) -> None:
    _stock_netto(fake_tjek, [_raw_offer("t-1", "Hakket oksekød 8-12%", 35, 45)])
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}
    _settings(client, shops=["netto"])

    run = _plan(client)

    prompt = fake_openai.prompts[-1]
    assert "[o1] Netto: Hakket oksekød 8-12% — 400 g — 35 kr (was 45 kr)" in prompt
    assert "until 2026-10-23" in prompt
    assert "Rema kaffe" not in prompt  # REMA isn't a preferred shop
    assert run["offerCount"] == 1
    assert run["offersUnavailable"] == []


def test_non_food_is_kept_out_of_the_prompt(client, fake_openai, fake_tjek) -> None:
    _stock_netto(
        fake_tjek,
        [
            _raw_offer("t-1", "Frisko isbæger"),  # "sko" inside a word is food
            _raw_offer("t-2", "Løbesko til herre"),
            _raw_offer("t-3", "Omo vaskemiddel"),
            _raw_offer("t-4", "Kyllingebryst", catalog="Netto Nonfood Uge 43"),
        ],
    )
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}

    _settings(client, shops=["netto"])
    _plan(client)

    prompt = fake_openai.prompts[-1]
    assert "Frisko isbæger" in prompt
    assert "Løbesko" not in prompt
    assert "vaskemiddel" not in prompt
    assert "Kyllingebryst" not in prompt  # printed in a non-food tilbudsavis


def test_library_matches_rank_ahead_of_bigger_discounts(
    client, fake_openai, fake_tjek
) -> None:
    _stock_netto(
        fake_tjek,
        [
            _raw_offer("t-1", "Chips", 10, 20),  # 50 % off, but not in a dish
            _raw_offer("t-2", "Løgismose kefir"),  # a brand, not an onion
            _raw_offer("t-3", "Samsø rødløg"),
        ],
    )
    client.post("/api/dishes", json={"title": "Suppe", "ingredients": "løg, smør"})
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}

    _settings(client, shops=["netto"])
    _plan(client)

    prompt = fake_openai.prompts[-1]
    assert prompt.index("[o1] Netto: Samsø rødløg") < prompt.index("Chips")
    assert prompt.index("Chips") < prompt.index("Løgismose kefir")


def test_offer_count_is_capped_at_the_household_limit(
    client, fake_openai, fake_tjek
) -> None:
    _stock_netto(fake_tjek, [_raw_offer(f"t-{i}", f"Vare {i}") for i in range(150)])
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}
    client.put("/api/prompt", json={"template": None, "offerLimit": 100})

    _settings(client, shops=["netto"])
    run = _plan(client)

    assert run["offerCount"] == 100
    assert "[o100]" in fake_openai.prompts[-1]
    assert "[o101]" not in fake_openai.prompts[-1]


def test_no_preferred_shops_plans_without_offers(client, fake_openai, fake_tjek) -> None:
    _stock_netto(fake_tjek, [_raw_offer("t-1", "Hakket oksekød")])
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}

    _settings(client, shops=[])
    run = _plan(client)

    assert run["status"] == "success"
    assert run["offerCount"] == 0
    assert "on offer" not in fake_openai.prompts[-1]
    assert fake_tjek.offer_calls == 0


def test_tjek_failure_plans_anyway_and_says_so(client, fake_openai, fake_tjek) -> None:
    fake_tjek.fail = True
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}

    _settings(client, shops=["netto", "rema-1000"])
    run = _plan(client)

    assert run["status"] == "success"
    assert run["offerCount"] == 0
    assert run["offersUnavailable"] == ["Netto", "Rema 1000"]


def test_cited_offers_are_stored_in_full(client, fake_openai, fake_tjek) -> None:
    _stock_netto(fake_tjek, [_raw_offer("t-1", "Hakket oksekød 8-12%", 35, 50)])
    fake_openai.canned = {
        "days": [
            {
                "day": 1,
                "suggestions": [
                    _suggestion(
                        "Chili",
                        [
                            {"offerId": "o1", "matchedIngredient": "hakket oksekød"},
                            {"offerId": "o1", "matchedIngredient": "hakket oksekød"},
                            {"offerId": "o99", "matchedIngredient": "trøffel"},
                        ],
                    )
                ],
            }
        ]
    }

    _settings(client, shops=["netto"])
    run = _plan(client)

    (discount,) = run["days"][0]["suggestions"][0]["discounts"]
    assert discount == {
        "offerId": "t-1",
        "productName": "Hakket oksekød 8-12%",
        "description": None,
        "shop": "Netto",
        "shopSlug": "netto",
        "price": 35,
        "originalPrice": 50,
        "discountPercent": 30.0,
        "unitSize": "400 g",
        "validFrom": "2026-10-17",
        "validUntil": "2026-10-23",
        "imageUrl": "https://img.example/t-1.webp",
        "matchedIngredient": "hakket oksekød",
        "matchedBy": "model",
    }
    # The archive keeps the full offer, not a reference to an expired one.
    archived = client.get(f"/api/planning-runs/{run['id']}").json()
    assert archived["days"][0]["suggestions"][0]["discounts"] == [discount]


def test_schema_asks_only_for_offer_references() -> None:
    from food_planer.planning import planning_json_schema

    suggestion = planning_json_schema()["properties"]["days"]["items"][
        "properties"
    ]["suggestions"]["items"]
    discount = suggestion["properties"]["discounts"]["items"]
    assert set(discount["properties"]) == {"offerId", "matchedIngredient"}


def test_preview_shows_the_offers(client, fake_tjek) -> None:
    _stock_netto(fake_tjek, [_raw_offer("t-1", "Hakket oksekød")])
    _settings(client, shops=["netto"])

    segments = client.post(
        "/api/prompt/preview",
        json={"template": "{{offers}}"},
    ).json()["segments"]

    assert segments[0]["variable"] == "offers"
    assert segments[0]["text"].startswith("[o1] Netto: Hakket oksekød")


def test_uncited_ingredients_are_matched_to_offers_by_name(
    client, fake_openai, fake_tjek
) -> None:
    _stock_netto(
        fake_tjek,
        [
            _raw_offer("t-1", "Netto hakket oksekød 8-12%", 35),
            _raw_offer("t-2", "Kapris i lage"),
            _raw_offer("t-3", "Jasmin ris"),
            _raw_offer("t-4", "Dava danske frilandsæg"),
        ],
    )
    suggestion = _suggestion("Chili", [])  # the model cited nothing
    suggestion["ingredients"] = [
        {"name": "hakket oksekød", "quantity": "400 g"},
        {"name": "ris", "quantity": "200 g"},
        {"name": "æg", "quantity": "2"},
        {"name": "sojasauce", "quantity": "2 spsk"},
    ]
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [suggestion]}]}

    _settings(client, shops=["netto"])
    run = _plan(client)

    discounts = run["days"][0]["suggestions"][0]["discounts"]
    by_ingredient = {d["matchedIngredient"]: d["productName"] for d in discounts}
    assert by_ingredient == {
        "hakket oksekød": "Netto hakket oksekød 8-12%",
        "ris": "Jasmin ris",  # a whole word beats the tail of "Kapris"
        "æg": "Dava danske frilandsæg",  # a compound's tail, confirmed by review
    }
    by = {d["matchedIngredient"]: d["matchedBy"] for d in discounts}
    assert by == {"hakket oksekød": "name", "ris": "name", "æg": "review"}


def test_shops_take_turns_in_the_capped_list(client, fake_openai, fake_tjek) -> None:
    fake_tjek.dealers = [{"id": "n1", "name": "Netto"}, {"id": "r1", "name": "REMA 1000"}]
    fake_tjek.offers = {
        "n1": [_raw_offer(f"n-{i}", f"Netto vare {i}") for i in range(150)],
        "r1": [_raw_offer(f"r-{i}", f"Rema vare {i}") for i in range(150)],
    }
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}
    client.put("/api/prompt", json={"template": None, "offerLimit": 100})

    _settings(client, shops=["netto", "rema-1000"])
    _plan(client)

    lines = [l for l in fake_openai.prompts[-1].splitlines() if l.startswith("[o")]
    assert len(lines) == 100
    assert sum("] Netto:" in l for l in lines) == 50
    assert sum("] REMA 1000:" in l for l in lines) == 50


def test_dish_titles_steer_the_ranking(client, fake_openai, fake_tjek) -> None:
    _stock_netto(
        fake_tjek, [_raw_offer("t-1", "Chips", 10, 20), _raw_offer("t-2", "Lasagneplader")]
    )
    client.post("/api/dishes", json={"title": "Lasagne"})  # a bare title
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}

    _settings(client, shops=["netto"])
    _plan(client)

    assert "[o1] Netto: Lasagneplader" in fake_openai.prompts[-1]


def test_every_run_writes_a_debug_trace(
    client, fake_openai, fake_tjek, data_dir
) -> None:
    import json

    _stock_netto(fake_tjek, [_raw_offer("t-1", "Netto hakket oksekød 8-12%")])
    raw = {
        "days": [
            {
                "day": 1,
                "suggestions": [
                    _suggestion(
                        "Chili", [{"offerId": "o1", "matchedIngredient": "hakket oksekød"}]
                    )
                ],
            }
        ]
    }
    fake_openai.canned = raw

    _settings(client, shops=["netto"])
    run = _plan(client)

    trace = json.loads((data_dir / "run_logs" / f"{run['id']}.json").read_text("utf-8"))
    assert trace["settings"]["shops"] == ["netto"]
    assert trace["offers"]["shownToModel"] == 1
    (call,) = trace["calls"]
    assert call["prompt"] == fake_openai.prompts[-1]
    # The raw output is the model's own citation, before the backend swapped
    # in the full offer.
    assert call["rawOutput"]["days"][0]["suggestions"][0]["discounts"] == [
        {"offerId": "o1", "matchedIngredient": "hakket oksekød"}
    ]
    assert trace["result"]["status"] == "success"
    assert trace["result"]["offersCitedByModel"] == 1


def test_beauty_products_are_not_food() -> None:
    from food_planer.discounts import is_food

    assert not is_food({"item_name": "Mood face creme"})
    assert is_food({"item_name": "Creme fraiche 18%"})


def test_name_matching_ignores_modifiers_and_accompaniments() -> None:
    from food_planer.discounts import offer_for_ingredient

    offers = [
        {"id": "1", "item_name": "Fløde-kartofler"},
        {"id": "2", "item_name": "San Marco Pizza med hvidløg & ost"},
        {"id": "3", "item_name": "Arla piskefløde 38%"},
    ]

    assert offer_for_ingredient("fløde", offers)["id"] == "3"
    assert offer_for_ingredient("hvidløg", offers) is None


def test_offer_limit_zero_lists_none_but_still_matches_by_name(
    client, fake_openai, fake_tjek
) -> None:
    _stock_netto(fake_tjek, [_raw_offer("t-1", "Netto hakket oksekød 8-12%")])
    fake_openai.canned = {"days": [{"day": 1, "suggestions": [_suggestion("Chili", [])]}]}
    client.put("/api/prompt", json={"template": None, "offerLimit": 0})

    _settings(client, shops=["netto"])
    run = _plan(client)

    assert run["offerCount"] == 0
    assert "[o1]" not in fake_openai.prompts[-1]
    (discount,) = run["days"][0]["suggestions"][0]["discounts"]
    assert discount["matchedBy"] == "name"


def test_seasoning_is_never_matched_and_salted_is_not_salt() -> None:
    from food_planer.discounts import offer_for_ingredient

    offers = [{"id": "1", "item_name": "Tørsaltet peber bacon"}]

    assert offer_for_ingredient("salt", offers) is None
    assert offer_for_ingredient("peber", offers) is None
    assert offer_for_ingredient("salt og peber", offers) is None
    assert offer_for_ingredient("bacon", offers)["id"] == "1"
