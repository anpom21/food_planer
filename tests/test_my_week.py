"""My week: the dishes chosen for each week, through the HTTP seam.

- ``POST /api/my-week`` files a Suggestion snapshot under this week's Monday,
  or under the Monday it's given; anything else is a 422;
- adding a title the week already has returns that entry (200, not created),
  so a dish is never listed twice — but the same dish can go in another week;
- ``GET /api/my-week`` returns this week's Monday and every entry, old weeks
  included; ``DELETE /api/my-week/{id}`` removes one (404 when it's gone);
- entries survive a restart.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from food_planer.app import current_week


def suggestion(title: str = "Lasagne") -> dict:
    return {
        "title": title,
        "description": "",
        "ingredients": [{"name": "pasta", "quantity": "500 g"}],
        "estimatedCost": 60,
        "prepTimeMinutes": 45,
        "sourceDish": None,
    }


def test_current_week_is_a_monday():
    assert date.fromisoformat(current_week()).weekday() == 0


def test_adds_to_this_week_by_default(client):
    resp = client.post("/api/my-week", json={"suggestion": suggestion()})
    assert resp.status_code == 201
    added = resp.json()
    assert added["created"] is True
    assert added["entry"]["week"] == current_week()
    assert added["entry"]["suggestion"]["title"] == "Lasagne"

    body = client.get("/api/my-week").json()
    assert body["currentWeek"] == current_week()
    assert [e["id"] for e in body["entries"]] == [added["entry"]["id"]]


def test_the_same_title_twice_in_a_week_is_one_entry(client):
    first = client.post("/api/my-week", json={"suggestion": suggestion()}).json()
    again = client.post("/api/my-week", json={"suggestion": suggestion(" lasagne ")})
    assert again.status_code == 200
    assert again.json() == {"entry": first["entry"], "created": False}
    assert len(client.get("/api/my-week").json()["entries"]) == 1


def test_files_under_a_given_week_and_keeps_old_weeks(client):
    last_week = (date.fromisoformat(current_week()) - timedelta(days=7)).isoformat()
    client.post("/api/my-week", json={"suggestion": suggestion(), "week": last_week})
    client.post("/api/my-week", json={"suggestion": suggestion()})
    weeks = [e["week"] for e in client.get("/api/my-week").json()["entries"]]
    assert weeks == [last_week, current_week()]


def test_a_week_must_be_a_monday(client):
    tuesday = (date.fromisoformat(current_week()) + timedelta(days=1)).isoformat()
    for week in (tuesday, "next week"):
        resp = client.post("/api/my-week", json={"suggestion": suggestion(), "week": week})
        assert resp.status_code == 422


def test_removes_an_entry(client):
    entry = client.post("/api/my-week", json={"suggestion": suggestion()}).json()["entry"]
    assert client.delete(f"/api/my-week/{entry['id']}").status_code == 204
    assert client.get("/api/my-week").json()["entries"] == []
    assert client.delete(f"/api/my-week/{entry['id']}").status_code == 404


def test_survives_a_restart(make_client, data_dir: Path):
    make_client(data_dir).post("/api/my-week", json={"suggestion": suggestion()})
    entries = make_client(data_dir).get("/api/my-week").json()["entries"]
    assert [e["suggestion"]["title"] for e in entries] == ["Lasagne"]
