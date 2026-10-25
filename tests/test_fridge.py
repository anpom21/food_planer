"""What is in the fridge, driven through the HTTP seam.

Two kinds of item: fresh items (keep for less than about a month), added and
removed by hand or found by a photo scan; and pantry staples, assumed always in
the house. Both reach the planning prompt. The common-items list starts from a
basic set and learns every name the household adds.
"""

from __future__ import annotations


def _add(client, items):
    resp = client.post("/api/fridge/items", json=items)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _names(items):
    return [i["name"] for i in items]


def _profile(client) -> str:
    resp = client.post(
        "/api/profiles/identify", json={"email": "a@example.com", "name": "A"}
    )
    return resp.json()["id"]


def test_an_empty_fridge_offers_the_basic_common_items(client) -> None:
    body = client.get("/api/fridge").json()
    assert body["fresh"] == [] and body["staples"] == []
    assert "Milk" in body["common"]["fresh"]
    assert "Rice" in body["common"]["staple"]


def test_added_items_are_grouped_by_kind_and_leave_the_common_list(client) -> None:
    body = _add(
        client,
        [{"name": "Milk", "kind": "fresh"}, {"name": "Rice", "kind": "staple"}],
    )
    assert _names(body["fresh"]) == ["Milk"]
    assert _names(body["staples"]) == ["Rice"]
    assert "Milk" not in body["common"]["fresh"]
    assert "Rice" not in body["common"]["staple"]
    assert body["fresh"][0]["addedAt"]


def test_the_same_item_is_never_listed_twice(client) -> None:
    _add(client, [{"name": "Milk", "kind": "fresh"}])
    body = _add(client, [{"name": "  milk ", "kind": "fresh"}])
    assert _names(body["fresh"]) == ["Milk"]


def test_a_removed_item_comes_back_as_a_common_item(client) -> None:
    body = _add(client, [{"name": "Rhubarb", "kind": "fresh"}])
    item_id = body["fresh"][0]["id"]

    body = client.delete(f"/api/fridge/items/{item_id}").json()
    assert body["fresh"] == []
    # Learnt from the household, and listed ahead of the basic items.
    assert body["common"]["fresh"][0] == "Rhubarb"
    # Removing again is a no-op, not an error.
    assert client.delete(f"/api/fridge/items/{item_id}").status_code == 200


def test_a_name_filed_under_the_other_kind_follows_the_household(client) -> None:
    # "Potatoes" is a basic staple; this household calls them fresh.
    body = _add(client, [{"name": "Potatoes", "kind": "fresh"}])
    client.delete(f"/api/fridge/items/{body['fresh'][0]['id']}")
    common = client.get("/api/fridge").json()["common"]
    assert "Potatoes" in common["fresh"]
    assert "Potatoes" not in common["staple"]


def test_the_fridge_survives_a_restart(make_client, data_dir) -> None:
    _add(make_client(data_dir), [{"name": "Eggs", "kind": "fresh"}])
    assert _names(make_client(data_dir).get("/api/fridge").json()["fresh"]) == ["Eggs"]


def test_an_unknown_kind_is_refused(client) -> None:
    resp = client.post("/api/fridge/items", json=[{"name": "Milk", "kind": "frozen"}])
    assert resp.status_code == 422


def test_a_scan_returns_the_items_without_saving_them(client, fake_openai) -> None:
    fake_openai.scan_output = {
        "items": [
            {"name": "milk", "kind": "fresh"},
            {"name": "Milk", "kind": "fresh"},
            {"name": "Ketchup", "kind": "staple"},
            {"name": " ", "kind": "fresh"},
        ]
    }
    resp = client.post(
        "/api/fridge/scan",
        files=[
            ("images", ("a.jpg", b"jpeg-bytes", "image/jpeg")),
            ("images", ("b.png", b"png-bytes", "image/png")),
        ],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == [
        {"name": "Milk", "kind": "fresh"},
        {"name": "Ketchup", "kind": "staple"},
    ]
    assert fake_openai.scans == [
        [("image/jpeg", b"jpeg-bytes"), ("image/png", b"png-bytes")]
    ]
    assert client.get("/api/fridge").json()["fresh"] == []


def test_a_scan_refuses_files_that_are_not_images(client) -> None:
    resp = client.post(
        "/api/fridge/scan", files=[("images", ("a.txt", b"hi", "text/plain"))]
    )
    assert resp.status_code == 422


def test_a_failed_scan_is_a_502(client, fake_openai) -> None:
    fake_openai.behaviour = "error"
    resp = client.post(
        "/api/fridge/scan", files=[("images", ("a.jpg", b"x", "image/jpeg"))]
    )
    assert resp.status_code == 502


def test_the_planning_prompt_names_fresh_items_and_staples(client, fake_openai) -> None:
    profile_id = _profile(client)
    _add(
        client,
        [{"name": "Chicken", "kind": "fresh"}, {"name": "Rice", "kind": "staple"}],
    )
    client.post("/api/planning-runs", json={"profileId": profile_id})
    prompt = fake_openai.prompts[-1]
    assert "fresh items at home" in prompt and "Chicken" in prompt
    assert "always in the house" in prompt and "Rice" in prompt

    summary = client.get("/api/planning-runs").json()[0]
    assert summary["fridgeSnippet"] == "Chicken"


def test_an_empty_fridge_leaves_no_trace_in_the_prompt(client, fake_openai) -> None:
    client.post("/api/planning-runs", json={"profileId": _profile(client)})
    assert "at home" not in fake_openai.prompts[-1]


def test_clear_empties_one_kind_and_keeps_the_names(client) -> None:
    client.post(
        "/api/fridge/items",
        json=[
            {"name": "Milk", "kind": "fresh"},
            {"name": "Chicken", "kind": "fresh"},
            {"name": "Rice", "kind": "staple"},
        ],
    )

    body = client.delete("/api/fridge/items", params={"kind": "fresh"}).json()

    assert body["fresh"] == []
    assert [i["name"] for i in body["staples"]] == ["Rice"]
    # Still one tap away: cleared names come back as common items.
    assert {"Milk", "Chicken"} <= set(body["common"]["fresh"])
    body = client.delete("/api/fridge/items", params={"kind": "staple"}).json()
    assert body["staples"] == []
    assert client.delete("/api/fridge/items", params={"kind": "nope"}).status_code == 422
