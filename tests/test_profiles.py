"""Identify-yourself and profile-switching, driven through the HTTP seam.

Issue #17 (parent PRD: Food Planner spec #14). Email is a backend lookup key;
`localStorage` on the frontend holds only a `profileId` pointer, so every
promise here is one the backend must keep on its own:

- a new email creates a Profile and hands it back as current;
- an existing email resolves to that same Profile, the typed name discarded,
  with no duplicate ever created;
- the stored pointer (`GET /api/profiles/{id}`) resolves to the same Profile
  with its PlanningSettings embedded, so a reload — or a cleared browser that
  retypes the email — costs nothing;
- the switcher (`GET /api/profiles`) lists everyone, and switching is just
  picking an id: no password, no re-auth.
"""

from __future__ import annotations

from pathlib import Path


def test_new_email_creates_a_current_profile(client) -> None:
    resp = client.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Ada"},
    )
    assert resp.status_code == 200
    profile = resp.json()
    assert len(profile["id"]) == 32  # UUID4 hex
    assert profile["email"] == "ada@example.com"
    assert profile["name"] == "Ada"
    # PlanningSettings are embedded so app startup is a single request.
    assert "settings" in profile


def test_existing_email_returns_same_profile_and_discards_typed_name(
    client,
) -> None:
    first = client.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Ada"},
    ).json()

    # Same email, a different spelling of the name.
    second = client.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Adele"},
    ).json()

    assert second["id"] == first["id"]
    assert second["name"] == "Ada"  # the typed name is discarded
    # No duplicate Profile was created.
    assert len(client.get("/api/profiles").json()) == 1


def test_email_match_is_case_and_whitespace_insensitive(client) -> None:
    first = client.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Ada"},
    ).json()
    again = client.post(
        "/api/profiles/identify",
        json={"email": "  Ada@Example.COM  ", "name": "Ada"},
    ).json()
    assert again["id"] == first["id"]
    assert len(client.get("/api/profiles").json()) == 1


def test_stored_pointer_resolves_to_the_same_profile_with_settings(
    client,
) -> None:
    created = client.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Ada"},
    ).json()

    # A reload fetches the full Profile from the backend using the pointer.
    resp = client.get(f"/api/profiles/{created['id']}")
    assert resp.status_code == 200
    fetched = resp.json()
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "Ada"
    assert fetched["settings"] == created["settings"]


def test_unknown_profile_id_is_a_stock_404(client) -> None:
    resp = client.get("/api/profiles/deadbeef")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Profile not found"}


def test_switcher_lists_every_profile_without_auth(client) -> None:
    client.post(
        "/api/profiles/identify", json={"email": "ada@example.com", "name": "Ada"}
    )
    client.post(
        "/api/profiles/identify",
        json={"email": "grace@example.com", "name": "Grace"},
    )

    listed = client.get("/api/profiles").json()
    assert {p["name"] for p in listed} == {"Ada", "Grace"}
    # Switching is just picking an id — no password, no re-auth step.
    for p in listed:
        assert client.get(f"/api/profiles/{p['id']}").status_code == 200


def test_cleared_browser_retyping_email_resolves_back_to_same_profile(
    make_client, data_dir: Path
) -> None:
    # Identify against one app instance...
    first = make_client(data_dir)
    original = first.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Ada"},
    ).json()

    # ...clearing localStorage loses the pointer, but the backend is the source
    # of truth, so a fresh app that retypes the email resolves the same Profile.
    second = make_client(data_dir)
    resolved = second.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Ada"},
    ).json()

    assert resolved["id"] == original["id"]
    assert resolved["settings"] == original["settings"]
    assert len(second.get("/api/profiles").json()) == 1


def test_profile_default_planning_settings_shape(client) -> None:
    profile = client.post(
        "/api/profiles/identify",
        json={"email": "ada@example.com", "name": "Ada"},
    ).json()
    settings = profile["settings"]
    assert settings["daysToPlan"] == 7
    assert settings["suggestionsPerDay"] == 2
    assert settings["priority"] == ["cheap", "quick", "delicious", "healthy"]
    assert settings["shops"] == []
    assert settings["inspiration"] == ""
