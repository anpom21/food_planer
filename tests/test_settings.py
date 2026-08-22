"""Per-Profile PlanningSettings, saved on their own through the HTTP seam.

Issue #19 (parent PRD: Food Planner spec #14). The Settings screen edits a
Profile's planning preferences — days-to-plan, suggestions-per-day, the
known-vs-unknown lean, the priority order and the Inspiration text — and saves
them without round-tripping name and email:

- ``PUT /api/profiles/{id}/settings`` takes settings alone;
- every field persists and reloads (proven by a fresh app against the same
  data/ directory);
- saving under one Profile leaves another Profile's settings untouched
  (ADR 0001: PlanningSettings are per-Profile);
- an unknown id is a stock 404.
"""

from __future__ import annotations

from pathlib import Path


def _identify(client, email: str, name: str) -> dict:
    return client.post(
        "/api/profiles/identify", json={"email": email, "name": name}
    ).json()


EDITED = {
    "daysToPlan": 5,
    "suggestionsPerDay": 4,
    "knownVsUnknownBias": 0.8,
    "priority": ["healthy", "delicious", "quick", "cheap"],
    "shops": [],
    "inspiration": "more Vietnamese food, less pasta",
}


def test_put_settings_accepts_settings_alone_without_name_or_email(client) -> None:
    profile = _identify(client, "ada@example.com", "Ada")

    resp = client.put(f"/api/profiles/{profile['id']}/settings", json=EDITED)

    assert resp.status_code == 200
    updated = resp.json()
    # Identity untouched — the settings save never carried name or email.
    assert updated["id"] == profile["id"]
    assert updated["email"] == "ada@example.com"
    assert updated["name"] == "Ada"
    assert updated["settings"] == EDITED


def test_saved_settings_persist_and_reload(make_client, data_dir: Path) -> None:
    first = make_client(data_dir)
    profile = _identify(first, "ada@example.com", "Ada")
    first.put(f"/api/profiles/{profile['id']}/settings", json=EDITED)

    # A fresh app against the same data/ reads the settings back from disk.
    second = make_client(data_dir)
    reloaded = second.get(f"/api/profiles/{profile['id']}").json()
    assert reloaded["settings"] == EDITED


def test_saved_priority_order_is_the_chosen_sequence(client) -> None:
    profile = _identify(client, "ada@example.com", "Ada")
    order = ["delicious", "cheap", "healthy", "quick"]
    resp = client.put(
        f"/api/profiles/{profile['id']}/settings",
        json={**EDITED, "priority": order},
    )
    assert resp.json()["settings"]["priority"] == order


def test_saving_one_profile_leaves_another_untouched(client) -> None:
    ada = _identify(client, "ada@example.com", "Ada")
    grace = _identify(client, "grace@example.com", "Grace")
    grace_settings = grace["settings"]

    client.put(f"/api/profiles/{ada['id']}/settings", json=EDITED)

    # Grace's settings are still the defaults — Ada's save touched only Ada.
    refetched = client.get(f"/api/profiles/{grace['id']}").json()
    assert refetched["settings"] == grace_settings
    assert refetched["settings"] != EDITED


def test_put_settings_unknown_profile_is_a_stock_404(client) -> None:
    resp = client.put("/api/profiles/deadbeef/settings", json=EDITED)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Profile not found"}
