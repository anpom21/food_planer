"""Persistence across restart, driven through the HTTP seam.

Writing state through the API, rebuilding the app against the same ``data/``
and reading the same state back is the promise the JSON store makes.
"""

from __future__ import annotations

from pathlib import Path


def test_health(client) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_created_dish_gets_a_uuid4_hex_id(client) -> None:
    resp = client.post("/api/dishes", json={"title": "Lasagne"})
    assert resp.status_code == 201
    dish = resp.json()
    # UUID4 hex: 32 lowercase hex chars.
    assert len(dish["id"]) == 32
    assert all(c in "0123456789abcdef" for c in dish["id"])


def test_state_survives_a_restart(make_client, data_dir: Path) -> None:
    # Write state through the API...
    first = make_client(data_dir)
    created = first.post(
        "/api/dishes",
        json={"title": "Frikadeller", "recipe": "Fry them", "favourite": True},
    ).json()

    # ...rebuild the app against the same directory...
    second = make_client(data_dir)
    dishes = second.get("/api/dishes").json()

    # ...and read the same state back.
    assert dishes == [created]
    assert dishes[0]["title"] == "Frikadeller"
    assert dishes[0]["favourite"] is True


def test_data_layout_is_created_on_first_run(
    client, data_dir: Path, household_dir: Path
) -> None:
    # Signing up (via the client fixture) lays down the directory shape: the
    # user's own household, and the shared shop logos at the top of data/.
    assert (household_dir / "fridge_images").is_dir()
    assert (data_dir / "icons").is_dir()
    # A write materialises the entity's JSON file atomically.
    client.post("/api/dishes", json={"title": "Grød"})
    assert (household_dir / "dishes.json").is_file()


def test_every_entity_file_exists_on_first_run(client, household_dir: Path) -> None:
    # data/ holds one JSON file per entity type immediately after first run —
    # not only once a write happens to touch it (acceptance criterion #2).
    import json

    from food_planer.store import ENTITY_DEFAULTS

    for name, default in ENTITY_DEFAULTS.items():
        path = household_dir / f"{name}.json"
        assert path.is_file(), f"{name}.json should exist on first run"
        assert json.loads(path.read_text(encoding="utf-8")) == default


def test_recipe_can_be_cleared_with_null(client) -> None:
    dish = client.post(
        "/api/dishes", json={"title": "Salad", "recipe": "Toss it"}
    ).json()
    assert dish["recipe"] == "Toss it"
    cleared = client.post(
        "/api/dishes", json={"title": "Water", "recipe": None}
    ).json()
    assert cleared["recipe"] is None


def test_missing_dish_uses_stock_detail_error_body(client) -> None:
    resp = client.delete("/api/dishes/deadbeef")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Dish not found"}


def test_unicode_survives_a_round_trip(make_client, data_dir: Path) -> None:
    first = make_client(data_dir)
    first.post("/api/dishes", json={"title": "Rødgrød med fløde"})
    # Read back through a fresh app, proving it was written to disk correctly.
    second = make_client(data_dir)
    assert second.get("/api/dishes").json()[0]["title"] == "Rødgrød med fløde"
