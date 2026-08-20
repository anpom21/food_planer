"""The Dish library CRUD contract, driven through the HTTP seam (issue #18).

A Dish needs only a title; ingredients, substitutes and recipe are optional
freeform text. ``PUT /api/dishes/{id}`` is a full replace, so omitting an
optional field (or sending it as ``null``) clears it. The library is a single
household-shared collection.
"""

from __future__ import annotations

from pathlib import Path


def test_dish_created_with_title_alone_leaves_optionals_empty(client) -> None:
    dish = client.post("/api/dishes", json={"title": "Lasagne"}).json()
    assert dish["title"] == "Lasagne"
    assert dish["ingredients"] is None
    assert dish["substitutes"] is None
    assert dish["recipe"] is None
    assert dish["favourite"] is False


def test_dish_round_trips_every_optional_field(client) -> None:
    dish = client.post(
        "/api/dishes",
        json={
            "title": "Frikadeller",
            "ingredients": "Pork mince, onion, egg, flour",
            "substitutes": "Beef mince works too",
            "recipe": "Mix, shape, fry in butter",
            "favourite": True,
        },
    ).json()
    assert dish["ingredients"] == "Pork mince, onion, egg, flour"
    assert dish["substitutes"] == "Beef mince works too"
    assert dish["recipe"] == "Mix, shape, fry in butter"
    assert dish["favourite"] is True


def test_put_is_a_full_replace(client) -> None:
    dish = client.post(
        "/api/dishes",
        json={"title": "Salad", "recipe": "Toss it", "favourite": True},
    ).json()
    updated = client.put(
        f"/api/dishes/{dish['id']}",
        json={"title": "Green Salad", "ingredients": "Leaves"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == dish["id"]
    assert body["title"] == "Green Salad"
    assert body["ingredients"] == "Leaves"
    # Fields absent from the replacement body are cleared, not preserved.
    assert body["recipe"] is None
    assert body["favourite"] is False


def test_put_recipe_null_clears_the_field(client) -> None:
    dish = client.post(
        "/api/dishes", json={"title": "Soup", "recipe": "Simmer everything"}
    ).json()
    body = client.put(
        f"/api/dishes/{dish['id']}",
        json={"title": "Soup", "recipe": None},
    ).json()
    assert body["recipe"] is None


def test_put_persists_and_is_visible_in_the_list(client) -> None:
    dish = client.post("/api/dishes", json={"title": "Pasta"}).json()
    client.put(
        f"/api/dishes/{dish['id']}",
        json={"title": "Pasta", "ingredients": "Spaghetti, oil, garlic"},
    )
    listed = client.get("/api/dishes").json()
    assert listed == [
        {
            "id": dish["id"],
            "title": "Pasta",
            "ingredients": "Spaghetti, oil, garlic",
            "substitutes": None,
            "recipe": None,
            "favourite": False,
        }
    ]


def test_put_missing_dish_is_404(client) -> None:
    resp = client.put("/api/dishes/deadbeef", json={"title": "Ghost"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Dish not found"}


def test_library_is_household_shared_across_restart(make_client, data_dir: Path) -> None:
    # A dish added under one app instance is visible under a freshly-built one
    # against the same data/ — the library is shared, not per-session.
    first = make_client(data_dir)
    first.post("/api/dishes", json={"title": "Rugbrød"})
    second = make_client(data_dir)
    assert [d["title"] for d in second.get("/api/dishes").json()] == ["Rugbrød"]
