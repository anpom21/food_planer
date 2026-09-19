"""The backend-owned catalog of Danish grocery chains and their logos.

Issue #20 (parent PRD: Food Planner spec #14). The Settings screen picks
preferred shops from a fixed list the app already knows, so nobody has to spell
"SuperBrugsen" exactly right for discounts to work later. The list is
backend-owned because the discount fetcher resolves each preferred shop to a
Tjek dealer id by name anyway — duplicating the mapping in the frontend would
create two lists that must agree.

- ``GET /api/shops`` returns ``[{slug, name, hasIcon}]`` for the fixed chains;
- slugs are lowercase, spaces hyphenated and æ/ø/å stripped;
- ``hasIcon`` reflects whether ``data/icons/<slug>.<ext>`` exists, so the
  frontend can pick the coloured-initial fallback without a failed request;
- ``GET /api/shops/{slug}/icon`` serves that file, or a stock 404;
- a slug carrying path separators can't escape ``data/icons/``;
- selected shops round-trip on the Profile's PlanningSettings.
"""

from __future__ import annotations

from pathlib import Path


def test_list_shops_returns_slug_name_and_has_icon(client) -> None:
    shops = client.get("/api/shops").json()

    assert isinstance(shops, list) and shops
    for shop in shops:
        assert set(shop) == {"slug", "name", "hasIcon"}
        assert isinstance(shop["hasIcon"], bool)

    names = {s["name"] for s in shops}
    assert {"Netto", "SuperBrugsen", "Rema 1000"} <= names


def test_slugs_are_lowercase_hyphenated_and_strip_danish_letters(client) -> None:
    by_name = {s["name"]: s["slug"] for s in client.get("/api/shops").json()}

    # Lowercase, and a space becomes a single hyphen.
    assert by_name["Rema 1000"] == "rema-1000"
    assert by_name["Coop 365"] == "coop-365"
    assert by_name["SuperBrugsen"] == "superbrugsen"
    # æ/ø/å are stripped outright, not transliterated: "Føtex" → "ftex".
    assert by_name["Føtex"] == "ftex"


def test_has_icon_false_and_icon_endpoint_404_when_no_file(client) -> None:
    shops = client.get("/api/shops").json()
    assert all(s["hasIcon"] is False for s in shops)  # empty data/icons/

    resp = client.get("/api/shops/netto/icon")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Shop icon not found"}


def test_icon_is_served_and_has_icon_flips_true(make_client, data_dir: Path) -> None:
    client = make_client(data_dir)  # Store creates data/icons/ on startup
    icon = data_dir / "icons" / "netto.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\nfake-logo-bytes")

    resp = client.get("/api/shops/netto/icon")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG\r\n\x1a\nfake-logo-bytes"

    netto = next(s for s in client.get("/api/shops").json() if s["slug"] == "netto")
    assert netto["hasIcon"] is True


def test_icon_slug_cannot_escape_the_icons_directory(client) -> None:
    # A path-traversal slug must not resolve a file outside data/icons/.
    resp = client.get("/api/shops/..%2f..%2fconftest/icon")
    assert resp.status_code == 404


def test_selected_shops_persist_on_settings_and_reload(
    make_client, data_dir: Path
) -> None:
    first = make_client(data_dir)
    profile = first.post(
        "/api/profiles/identify", json={"email": "ada@example.com", "name": "Ada"}
    ).json()
    settings = {**profile["settings"], "shops": ["netto", "rema-1000", "my corner shop"]}
    first.put(f"/api/profiles/{profile['id']}/settings", json=settings)

    second = make_client(data_dir)
    reloaded = second.get(f"/api/profiles/{profile['id']}").json()
    assert reloaded["settings"]["shops"] == ["netto", "rema-1000", "my corner shop"]
