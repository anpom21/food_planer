"""Only imported recipes that use a fresh item or an offer reach the planner.

- an ingredient line is cut down to the name it gives ("500 g porre, i ringe"
  → "porre");
- an English Fridge item finds the Danish ingredient ("Leek" → "porre");
- a recipe using neither a fresh item nor an offer is left out;
- a pantry staple never makes a recipe relevant, even when it is on offer, and
  neither does an offer on something already in the fridge;
- rare matches outrank common ones: using up the chicken beats the butter;
- the planning prompt lists the matching dinner recipes and nothing else, and
  ``GET /api/recipes/matches`` shows the same ranking with what each one uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from food_planer.fridge import OnHand
from food_planer.recipes.matching import ingredient_name, match_recipes
from food_planer.recipes.scraper import write_json_atomic


def _recipe(title: str, *lines: str, categories: tuple[str, ...] = ("Aftensmad",)) -> dict[str, Any]:
    return {
        "source": "test",
        "url": f"https://r.test/{title.lower().replace(' ', '-')}/",
        "title": title,
        "thumbnail": None,
        "ingredients": [{"text": line, "group": None} for line in lines],
        "servings": None,
        "total_time": None,
        "categories": list(categories),
    }


def _offer(offer_id: str, item_name: str, shop: str = "Netto") -> dict[str, Any]:
    return {"id": offer_id, "item_name": item_name, "shop": shop, "price": 20}


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ("500 g porre, i ringe", "porre"),
        ("1 dåse grønne linser, drænet og skyllet", "linser"),
        ("1 dl cremefraiche 18 %", "cremefraiche"),
        ("1 spsk smør, til stegning", "smør"),
        ("2 spsk olivenolie til stegning", "olivenolie"),
        ("salt og friskkværnet peber", "salt"),
        ("100 g sorte oliven uden sten", "oliven"),
        ("1 håndfuld frisk koriander, finthakket", "koriander"),
        ("½ øko citron, fintrevet skal", "citron"),
        ("400 g kyllingefilet", "kyllingefilet"),
    ],
)
def test_ingredient_name_cuts_a_line_down_to_what_it_names(line: str, name: str) -> None:
    assert ingredient_name(line) == name


def test_fresh_items_match_in_danish_and_unrelated_recipes_are_dropped() -> None:
    soup = _recipe("Porresuppe", "500 g porre, i ringe", "1 liter bouillon")
    cake = _recipe("Kage", "200 g hvedemel", "100 g sukker")

    matches = match_recipes([soup, cake], OnHand(fresh=["Leek"]), offers=[])

    assert [m.recipe["title"] for m in matches] == ["Porresuppe"]
    assert matches[0].fresh == {"Leek": "porre"}


def test_an_offer_makes_a_recipe_relevant_unless_it_is_a_staple() -> None:
    chili = _recipe("Chili", "500 g hakket oksekød", "2 løg, hakket")
    onion_soup = _recipe("Løgsuppe", "1 kg løg", "1 liter bouillon")
    offers = [_offer("o1", "Hakket oksekød 8-12%"), _offer("o2", "Samsø løg")]

    matches = match_recipes([chili, onion_soup], OnHand(staples=["Onions"]), offers)

    assert [m.recipe["title"] for m in matches] == ["Chili"]
    assert [(o["ingredient"], o["offer"]["id"], o["review"]) for o in matches[0].offers] == [
        ("hakket oksekød", "o1", False)
    ]


def test_an_offer_on_something_already_in_the_fridge_does_not_count() -> None:
    omelet = _recipe("Omelet", "4 æg")

    matches = match_recipes([omelet], OnHand(fresh=["Eggs"]), [_offer("o1", "Frilandsæg")])

    assert matches[0].fresh == {"Eggs": "æg"}
    assert matches[0].offers == []


def test_rare_matches_outrank_common_ones() -> None:
    # Butter is in every recipe; chicken in one. Using up the chicken wins,
    # though the butter recipes come first on the site.
    recipes = [_recipe(f"Smørret {n}", "50 g smør", "1 kg kartofler") for n in range(5)]
    recipes.append(_recipe("Kyllingeret", "50 g smør", "400 g kyllingebryst"))

    matches = match_recipes(recipes, OnHand(fresh=["Butter", "Chicken"]), [])

    assert matches[0].recipe["title"] == "Kyllingeret"
    assert matches[0].fresh == {"Butter": "smør", "Chicken": "kyllingebryst"}


# --- Through the API -------------------------------------------------------


def _store_recipes(data_dir: Path, recipes: list[dict[str, Any]]) -> None:
    write_json_atomic(data_dir / "recipes" / "test.json", {"recipes": recipes})


def _setup(client, fake_tjek, data_dir: Path) -> str:
    _store_recipes(
        data_dir,
        [
            _recipe("Porresuppe", "500 g porre, i ringe"),
            _recipe("Chili con carne", "500 g hakket oksekød", "2 løg"),
            _recipe("Pasta med pesto", "400 g pasta", "1 glas pesto"),
            _recipe("Porrekage", "2 porrer", categories=("Kager",)),  # not dinner
        ],
    )
    client.post(
        "/api/fridge/items",
        json=[{"name": "Leek", "kind": "fresh"}, {"name": "Onions", "kind": "staple"}],
    )
    fake_tjek.dealers = [{"id": "n1", "name": "Netto"}]
    fake_tjek.offers = {
        "n1": [
            {
                "id": "t-1",
                "heading": "Hakket oksekød 8-12%",
                "description": None,
                "pricing": {"price": 35, "pre_price": 45, "currency": "DKK"},
                "quantity": None,
                "run_from": "2026-10-16T22:00:00+0000",
                "run_till": "2026-10-23T21:59:59+0000",
                "category_ids": [],
                "images": {},
                "catalog_label": "Netto Uge 43",
            }
        ]
    }
    profile_id = client.post(
        "/api/profiles/identify", json={"email": "ada@ex.com", "name": "Ada"}
    ).json()["id"]
    client.put(
        f"/api/profiles/{profile_id}/settings",
        json={"daysToPlan": 1, "suggestionsPerDay": 1, "shops": ["netto"]},
    )
    return profile_id


def test_the_prompt_lists_only_matching_dinner_recipes(
    client, fake_openai, fake_tjek, data_dir: Path
) -> None:
    profile_id = _setup(client, fake_tjek, data_dir)
    fake_openai.canned = {"days": []}

    client.post("/api/planning-runs", json={"profileId": profile_id})

    prompt = fake_openai.prompts[-1]
    # Refs follow the ranking; an offer in the prompt's list carries its [id].
    assert "] Porresuppe — uses up: porre" in prompt
    assert "] Chili con carne — on offer: hakket oksekød (Netto [o1])" in prompt
    assert "Pasta med pesto" not in prompt  # neither fresh nor on offer
    assert "Porrekage" not in prompt  # a cake, not a dinner


def test_matches_endpoint_explains_each_recipe(client, fake_tjek, data_dir: Path) -> None:
    profile_id = _setup(client, fake_tjek, data_dir)

    matches = client.get("/api/recipes/matches", params={"profileId": profile_id}).json()

    by_title = {m["title"]: m for m in matches}
    assert set(by_title) == {"Porresuppe", "Chili con carne"}
    assert by_title["Porresuppe"]["fresh"] == [{"item": "Leek", "ingredient": "porre"}]
    assert by_title["Chili con carne"]["offers"] == [
        {
            "ingredient": "hakket oksekød", "shop": "Netto",
            "productName": "Hakket oksekød 8-12%", "price": 35, "review": False,
        }
    ]
    assert all(m["inPrompt"] for m in matches)
    assert client.get("/api/recipes/matches", params={"profileId": "nobody"}).status_code == 404


# --- Linking a Suggestion back to its recipe -------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30 min.", 30),
        ("1 time 15 min.", 75),
        ("1½ time", 90),
        ("2 timer", 120),
        ("2 dage", 2880),
        ("Array", None),  # what valdemarsro prints for one recipe
        (None, None),
    ],
)
def test_minutes_reads_a_recipes_time(text: str | None, expected: int | None) -> None:
    from food_planer.recipes.matching import minutes

    assert minutes(text) == expected


def _suggestion(title: str, source_recipe: str | None, *ingredients: str) -> dict[str, Any]:
    return {
        "title": title,
        "description": "Dinner.",
        "ingredients": [{"name": n, "quantity": "1"} for n in ingredients],
        "estimatedCost": 60.0,
        "prepTimeMinutes": 25,
        "sourceDish": None,
        "sourceRecipe": source_recipe,
        "discounts": [],
    }


def test_a_suggestion_links_to_its_recipe_with_real_times(
    client, fake_openai, fake_tjek, data_dir: Path
) -> None:
    profile_id = _setup(client, fake_tjek, data_dir)
    soup = _recipe("Porresuppe", "500 g porre, i ringe")
    soup.update(thumbnail="https://r.test/porre.jpg", total_time="1 time 10 min.",
                work_time="20 min.", servings="4 pers.")
    _store_recipes(data_dir, [soup])
    fake_openai.canned = {
        "days": [
            {
                "day": 1,
                "suggestions": [
                    # Brackets copied from the prompt are fine.
                    _suggestion("Porresuppe", "[r1]", "porre", "salt", "rugbrød"),
                    _suggestion("Opfundet ret", "r9"),  # a ref the prompt never had
                ],
            }
        ]
    }

    run = client.post("/api/planning-runs", json={"profileId": profile_id}).json()

    linked, invented = run["days"][0]["suggestions"]
    assert linked["recipe"] == {
        "title": "Porresuppe",
        "url": "https://r.test/porresuppe/",
        "source": "test",
        "thumbnail": "https://r.test/porre.jpg",
        "totalTime": "1 time 10 min.",
        "workTime": "20 min.",
        "servings": "4 pers.",
    }
    assert linked["prepTimeMinutes"] == 70  # the recipe's time, not the model's 25
    assert "sourceRecipe" not in linked
    assert invented["recipe"] is None
    assert invented["prepTimeMinutes"] == 25
    # porre is in the fridge (Leek); salt and rugbrød are neither fresh nor staples here.
    haves = {i["name"]: i["have"] for i in linked["ingredients"]}
    assert haves == {"porre": "fresh", "salt": None, "rugbrød": None}


def test_ingredients_we_have_are_marked_fresh_or_staple(
    client, fake_openai, fake_tjek, data_dir: Path
) -> None:
    profile_id = _setup(client, fake_tjek, data_dir)  # Leek fresh, Onions staple
    fake_openai.canned = {
        "days": [{"day": 1, "suggestions": [_suggestion("Suppe", None, "porrer", "rødløg", "fløde")]}]
    }

    run = client.post("/api/planning-runs", json={"profileId": profile_id}).json()

    haves = {i["name"]: i["have"] for i in run["days"][0]["suggestions"][0]["ingredients"]}
    assert haves == {"porrer": "fresh", "rødløg": "staple", "fløde": None}
    recipes = client.get("/api/recipes").json()
    soup = next(r for r in recipes if r["title"] == "Porresuppe")
    assert soup["ingredients"][0]["have"] == "fresh"


def test_uncertain_recipe_offers_are_marked_for_the_planner_to_check(
    client, fake_openai, fake_tjek, data_dir: Path
) -> None:
    profile_id = _setup(client, fake_tjek, data_dir)
    _store_recipes(data_dir, [_recipe("Burger", "4 burgerboller")])
    fake_tjek.offers["n1"][0]["heading"] = "Salling Princip briocheburgerboller"
    fake_openai.canned = {"days": []}

    client.post("/api/planning-runs", json={"profileId": profile_id})

    prompt = fake_openai.prompts[-1]
    assert '[r1] Burger — check offer: burgerboller ≈ "Salling Princip briocheburgerboller"' in prompt
    assert '"check offer" marks a product that may not be the ingredient' in prompt
    matches = client.get("/api/recipes/matches", params={"profileId": profile_id}).json()
    assert matches[0]["offers"][0]["review"] is True
