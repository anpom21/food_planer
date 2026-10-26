"""The household's PlanningSettings, one shared set, through the HTTP seam.

The Settings screen edits the household's planning preferences — days-to-plan,
suggestions-per-day, the known-vs-unknown lean, the priority order, preferred
shops, the Inspiration text and the online-recipe mode:

- ``GET /api/settings`` returns every field, defaulted on a fresh install;
- ``PUT /api/settings`` is a full replace: it returns what was saved, and an
  omitted field reverts to its default;
- every field persists and reloads (proven by a fresh app against the same
  data/ directory);
- the priority order is saved as the chosen sequence;
- a household from the per-profile era adopts the first profile's settings
  from a legacy ``data/profiles.json`` once, leaving that file untouched — and
  never over settings it already has.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "daysToPlan": 7,
    "suggestionsPerDay": 2,
    "knownVsUnknownBias": 0.5,
    "priority": ["cheap", "quick", "delicious", "healthy"],
    "shops": [],
    "inspiration": "",
    "recipeMode": "mix",
}

EDITED = {
    "daysToPlan": 5,
    "suggestionsPerDay": 4,
    "knownVsUnknownBias": 0.8,
    "priority": ["healthy", "delicious", "quick", "cheap"],
    "shops": [],
    "inspiration": "more Vietnamese food, less pasta",
    "recipeMode": "only",
}


def test_a_fresh_install_has_the_default_settings(client) -> None:
    resp = client.get("/api/settings")

    assert resp.status_code == 200
    assert resp.json() == DEFAULTS


def test_put_settings_saves_and_returns_them(client) -> None:
    resp = client.put("/api/settings", json=EDITED)

    assert resp.status_code == 200
    assert resp.json() == EDITED
    assert client.get("/api/settings").json() == EDITED


def test_put_is_a_full_replace_so_omitted_fields_revert(client) -> None:
    client.put("/api/settings", json=EDITED)

    resp = client.put("/api/settings", json={"daysToPlan": 3})

    assert resp.json() == {**DEFAULTS, "daysToPlan": 3}
    assert client.get("/api/settings").json() == {**DEFAULTS, "daysToPlan": 3}


def test_saved_settings_persist_and_reload(make_client, data_dir: Path) -> None:
    first = make_client(data_dir)
    first.put("/api/settings", json=EDITED)

    # A fresh app against the same data/ reads the settings back from disk.
    second = make_client(data_dir)
    assert second.get("/api/settings").json() == EDITED


def test_saved_priority_order_is_the_chosen_sequence(client) -> None:
    order = ["delicious", "cheap", "healthy", "quick"]
    resp = client.put("/api/settings", json={**EDITED, "priority": order})
    assert resp.json()["priority"] == order


def _write_legacy_profiles(data_dir: Path, settings: dict) -> str:
    profiles = [
        {"id": "p1", "email": "ada@example.com", "name": "Ada", "settings": settings},
        {
            "id": "p2", "email": "bob@example.com", "name": "Bob",
            "settings": {**DEFAULTS, "inspiration": "Bob's wishes"},
        },
    ]
    text = json.dumps(profiles)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "profiles.json").write_text(text, "utf-8")
    return text


def test_legacy_profile_settings_are_adopted_once(make_client, data_dir: Path) -> None:
    legacy = _write_legacy_profiles(data_dir, EDITED)

    client = make_client(data_dir)

    # The first profile's settings become the household's...
    assert client.get("/api/settings").json() == EDITED
    # ...and the legacy file is left exactly as it was.
    assert (data_dir / "profiles.json").read_text("utf-8") == legacy


def test_existing_settings_are_not_overwritten_by_legacy_profiles(
    make_client, data_dir: Path
) -> None:
    first = make_client(data_dir)
    first.put("/api/settings", json={**DEFAULTS, "daysToPlan": 3})
    _write_legacy_profiles(data_dir, EDITED)

    second = make_client(data_dir)

    assert second.get("/api/settings").json() == {**DEFAULTS, "daysToPlan": 3}


def test_an_unreadable_legacy_profiles_file_is_ignored(make_client, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "profiles.json").write_text("{not json", "utf-8")

    client = make_client(data_dir)

    assert client.get("/api/settings").json()["recipeMode"] == "mix"  # defaults
