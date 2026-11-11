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
- a chain with no logo yet gets its Tjek dealer's logo on the first listing,
  tried once per run; a failed fetch keeps the initials and never fails the
  list, and a logo dropped in by hand is never overwritten;
- selected shops round-trip on the household's PlanningSettings.
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
    settings = {**first.get("/api/settings").json(), "shops": ["netto", "rema-1000", "my corner shop"]}
    first.put("/api/settings", json=settings)

    second = make_client(data_dir)
    reloaded = second.get("/api/settings").json()
    assert reloaded["shops"] == ["netto", "rema-1000", "my corner shop"]


# --- Logos fetched from the chains' Tjek dealers -----------------------------

PNG = b"\x89PNG\r\n\x1a\nnetto-logo"


def test_a_missing_logo_is_fetched_from_the_tjek_dealer(client, fake_tjek, data_dir: Path) -> None:
    fake_tjek.dealers = [
        {"id": "n1", "name": "Netto", "logo": "https://img.test/netto.png"},
        {"id": "r1", "name": "REMA 1000"},  # Tjek has no logo for it
    ]
    fake_tjek.images = {"https://img.test/netto.png": (PNG, "image/png")}

    shops = {s["slug"]: s for s in client.get("/api/shops").json()}

    assert shops["netto"]["hasIcon"] is True
    assert (data_dir / "icons" / "netto.png").read_bytes() == PNG
    assert client.get("/api/shops/netto/icon").content == PNG
    assert shops["rema-1000"]["hasIcon"] is False  # keeps its initials


def test_logos_are_tried_once_per_run_and_never_fail_the_list(client, fake_tjek) -> None:
    fake_tjek.dealers = [{"id": "n1", "name": "Netto", "logo": "https://img.test/broken.png"}]

    first = client.get("/api/shops")
    calls = (fake_tjek.dealer_calls, fake_tjek.image_calls)
    second = client.get("/api/shops")

    assert first.status_code == second.status_code == 200
    assert calls == (1, 1)  # the failed download
    assert (fake_tjek.dealer_calls, fake_tjek.image_calls) == calls  # not retried


def test_a_logo_dropped_in_by_hand_is_kept(make_client, fake_tjek, data_dir: Path) -> None:
    client = make_client(data_dir)
    (data_dir / "icons" / "netto.svg").write_text("<svg/>", "utf-8")
    fake_tjek.dealers = [{"id": "n1", "name": "Netto", "logo": "https://img.test/netto.png"}]
    fake_tjek.images = {"https://img.test/netto.png": (PNG, "image/png")}

    client.get("/api/shops")

    assert not (data_dir / "icons" / "netto.png").exists()
    assert client.get("/api/shops/netto/icon").text == "<svg/>"


def test_save_icon_only_writes_images_under_a_safe_slug(tmp_path: Path) -> None:
    from food_planer.shops import save_icon

    assert save_icon(tmp_path, "netto", PNG, "image/png; charset=binary") == tmp_path / "netto.png"
    assert save_icon(tmp_path, "netto", b"<html>", "text/html") is None
    assert save_icon(tmp_path, "../evil", PNG, "image/png") is None
    assert save_icon(tmp_path, "lidl", b"", "image/png") is None
