"""ShoppingList merging, driven through the HTTP seam.

The household keeps one persistent, shared shopping list. Ingredients arrive in
bulk from a plan or one at a time by hand, and the backend merges them into one
row per ingredient: the headline amount summed across every dish, each dish's
share preserved, and mismatched units joined rather than silently summed.

Merging is the fiddliest logic in the app, so it is built test-first as a pure
function exercised behind ``/api/shopping-list`` (spec.md → "ShoppingList" and
"Testing").
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path


def _add(client, items):
    resp = client.post("/api/shopping-list/items", json=items)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_empty_list_starts_empty(client) -> None:
    assert client.get("/api/shopping-list").json() == []


def test_several_dishes_wanting_one_ingredient_make_one_row(client) -> None:
    _add(
        client,
        [
            {
                "name": "Potatoes",
                "quantity": "800 g",
                "source": {"suggestionTitle": "Frikadeller", "kind": "known"},
            },
            {
                "name": "Potatoes",
                "quantity": "400 g",
                "source": {"suggestionTitle": "Miso-glazed salmon", "kind": "unknown"},
            },
        ],
    )
    rows = client.get("/api/shopping-list").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Potatoes"
    # Total is the sum across every dish...
    assert row["totalQuantity"] == "1200 g"
    # ...and each dish's share is preserved, as a bare unitless number.
    shares = {(s["dishTitle"], s["kind"], s["share"]) for s in row["sources"]}
    assert shares == {
        ("Frikadeller", "known", "800"),
        ("Miso-glazed salmon", "unknown", "400"),
    }
    assert len(row["lineIds"]) == 2


def test_bare_numbers_sum_without_a_unit(client) -> None:
    _add(
        client,
        [
            {"name": "Onions", "quantity": "2", "source": {"suggestionTitle": "Chili", "kind": "known"}},
            {"name": "Onions", "quantity": "2", "source": {"suggestionTitle": "Lasagne", "kind": "known"}},
            {"name": "Onions", "quantity": "1", "source": {"suggestionTitle": "Frikadeller", "kind": "known"}},
        ],
    )
    (row,) = client.get("/api/shopping-list").json()
    assert row["totalQuantity"] == "5"
    assert sorted(s["share"] for s in row["sources"]) == ["1", "2", "2"]


def test_mismatched_units_are_joined_not_summed(client) -> None:
    _add(
        client,
        [
            {"name": "Milk", "quantity": "5 dl", "source": {"suggestionTitle": "Sauce", "kind": "known"}},
            {"name": "Milk", "quantity": "2 cups", "source": {"suggestionTitle": "Pancakes", "kind": "unknown"}},
        ],
    )
    (row,) = client.get("/api/shopping-list").json()
    # "5 dl and 2 cups" must never quietly become a wrong number.
    assert row["totalQuantity"] == "5 dl and 2 cups"
    # Each dish keeps its own unit rather than a bare, ambiguous number.
    shares = {s["dishTitle"]: s["share"] for s in row["sources"]}
    assert shares == {"Sauce": "5 dl", "Pancakes": "2 cups"}


def test_hand_added_item_has_no_dish_source(client) -> None:
    _add(client, [{"name": "Coffee", "quantity": "500 g", "source": None}])
    (row,) = client.get("/api/shopping-list").json()
    assert row["name"] == "Coffee"
    assert row["totalQuantity"] == "500 g"
    # Distinguishable from dish-sourced items: no dish behind the source entry.
    assert row["sources"] == [{"dishTitle": None, "kind": None, "share": "500"}]


def test_hand_added_and_dish_sourced_merge_into_one_row(client) -> None:
    _add(
        client,
        [
            {"name": "Butter", "quantity": "50 g", "source": {"suggestionTitle": "Cookies", "kind": "known"}},
            {"name": "Butter", "quantity": "100 g", "source": None},
        ],
    )
    (row,) = client.get("/api/shopping-list").json()
    assert row["totalQuantity"] == "150 g"
    kinds = {s["dishTitle"] for s in row["sources"]}
    assert kinds == {"Cookies", None}


def test_removing_a_merged_row_removes_every_underlying_line(client) -> None:
    _add(
        client,
        [
            {"name": "Rice", "quantity": "200 g", "source": {"suggestionTitle": "Curry", "kind": "known"}},
            {"name": "Rice", "quantity": "300 g", "source": {"suggestionTitle": "Risotto", "kind": "unknown"}},
        ],
    )
    (row,) = client.get("/api/shopping-list").json()
    assert len(row["lineIds"]) == 2
    resp = client.post("/api/shopping-list/items/remove", json={"lineIds": row["lineIds"]})
    assert resp.status_code == 200
    assert client.get("/api/shopping-list").json() == []


def test_removing_one_row_leaves_the_others(client) -> None:
    _add(
        client,
        [
            {"name": "Apples", "quantity": "3", "source": None},
            {"name": "Pears", "quantity": "2", "source": None},
        ],
    )
    rows = {r["name"]: r for r in client.get("/api/shopping-list").json()}
    client.post("/api/shopping-list/items/remove", json={"lineIds": rows["Apples"]["lineIds"]})
    remaining = client.get("/api/shopping-list").json()
    assert [r["name"] for r in remaining] == ["Pears"]


def test_list_is_shared_and_survives_a_restart(make_client, data_dir: Path) -> None:
    first = make_client(data_dir)
    first.post(
        "/api/shopping-list/items",
        json=[{"name": "Salt", "quantity": "1 kg", "source": None}],
    )
    # A fresh app against the same data/ sees the same shared list.
    second = make_client(data_dir)
    (row,) = second.get("/api/shopping-list").json()
    assert row["name"] == "Salt"
    assert row["totalQuantity"] == "1 kg"


def test_shopping_list_json_has_no_ticked_field(client, data_dir: Path) -> None:
    _add(client, [{"name": "Eggs", "quantity": "6", "source": None}])
    raw = (data_dir / "shopping_list.json").read_text(encoding="utf-8")
    assert "ticked" not in raw
    stored = json.loads(raw)
    for item in stored["items"]:
        assert "ticked" not in item


# --- Export: text (Copy list) and CSV (issue #30) --------------------------
# The list leaves the app two ways that work on a plain-HTTP home network: a
# plain-text preview to paste into a chat, and a shopping-list.csv download.
# Both are generated behind the seam so their fiddly bits — per-dish shares in
# brackets, CSV quoting, the UTF-8 BOM — are unit-testable without a browser.


def test_text_export_shows_total_with_per_dish_shares_in_brackets(client) -> None:
    _add(
        client,
        [
            {"name": "Onions", "quantity": "2", "source": {"suggestionTitle": "Chili con carne", "kind": "known"}},
            {"name": "Onions", "quantity": "2", "source": {"suggestionTitle": "Lasagne", "kind": "known"}},
            {"name": "Onions", "quantity": "1", "source": {"suggestionTitle": "Frikadeller", "kind": "known"}},
            {"name": "Minced beef", "quantity": "500 g", "source": {"suggestionTitle": "Chili con carne", "kind": "known"}},
        ],
    )
    text = client.get("/api/shopping-list/export.txt").text
    # A shared ingredient carries its total and each dish's share in brackets.
    assert "Onions — 5 (Chili con carne 2, Lasagne 2, Frikadeller 1)" in text
    # A single-dish ingredient shows its total but no bracketed breakdown.
    assert "Minced beef — 500 g" in text
    assert "Minced beef — 500 g (" not in text


def test_csv_export_has_its_columns_provenance_notes_and_offers(client) -> None:
    _add(
        client,
        [
            {"name": "Potatoes", "quantity": "800 g", "source": {"suggestionTitle": "Frikadeller", "kind": "known"}},
            {"name": "Potatoes", "quantity": "400 g", "source": {"suggestionTitle": "Miso-glazed salmon", "kind": "unknown"}},
            {"name": "Minced beef", "quantity": "500 g", "source": {"suggestionTitle": "Chili con carne", "kind": "known"},
             "offer": {"shop": "Netto", "shopSlug": "netto", "productName": "Hakket oksekød 8-12%", "price": 35}},
        ],
    )
    body = client.get("/api/shopping-list/export.csv").text
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    assert rows[0] == ["Ingredient", "Quantity", "Notes", "Shop", "Offer"]
    parsed = {r[0]: r for r in rows[1:]}
    # Shared: one note per dish joined with "; ", each carrying that dish's share.
    assert parsed["Potatoes"] == [
        "Potatoes",
        "1200 g",
        "Frikadeller 800; Miso-glazed salmon 400",
        "",
        "",
    ]
    # Single dish: the note is just the dish name, since Quantity already holds
    # it; the offer it was on keeps its shop.
    assert parsed["Minced beef"] == [
        "Minced beef", "500 g", "Chili con carne", "Netto", "Hakket oksekød 8-12% (35 kr)",
    ]
    # Grouped by shop: the offer comes first.
    assert [r[0] for r in rows[1:]] == ["Minced beef", "Potatoes"]


def test_csv_export_hand_added_item_carries_its_own_note(client) -> None:
    _add(client, [{"name": "Coffee", "quantity": "500 g", "source": None, "note": "we're just out"}])
    body = client.get("/api/shopping-list/export.csv").text
    rows = {r[0]: r for r in csv.reader(io.StringIO(body.lstrip("﻿")))}
    assert rows["Coffee"] == ["Coffee", "500 g", "we're just out", "", ""]


def test_csv_export_quotes_fields_containing_commas_or_quotes(client) -> None:
    _add(
        client,
        [
            {"name": "Beans", "quantity": "1 can", "source": {"suggestionTitle": 'Chili, "hot"', "kind": "known"}},
        ],
    )
    body = client.get("/api/shopping-list/export.csv").text
    # The comma and the doubled quotes are quoted per RFC 4180...
    assert '"Chili, ""hot"""' in body
    # ...and it round-trips back to the original string through a CSV reader.
    rows = {r[0]: r for r in csv.reader(io.StringIO(body.lstrip("﻿")))}
    assert rows["Beans"][2] == 'Chili, "hot"'


def test_csv_export_starts_with_bom_and_preserves_danish_characters(client) -> None:
    _add(client, [{"name": "Rødløg", "quantity": "3", "source": None, "note": "øko hvis muligt"}])
    resp = client.get("/api/shopping-list/export.csv")
    body = resp.text
    # A UTF-8 BOM so Excel reads æ/ø/å back correctly.
    assert body.startswith("﻿")
    assert "Rødløg" in body
    assert "øko hvis muligt" in body
    # Downloaded, not rendered inline.
    assert "shopping-list.csv" in resp.headers.get("content-disposition", "")


# --- Export to the iPhone's Påmindelser, via an iOS Shortcut ------------------


def test_reminders_export_has_a_title_and_a_subtext_per_row(client) -> None:
    _add(
        client,
        [
            {"name": "hakket oksekød", "quantity": "500 g",
             "source": {"suggestionTitle": "Chili con carne", "kind": "known"}},
            {"name": "hakket oksekød", "quantity": "500 g",
             "source": {"suggestionTitle": "Lasagne", "kind": "known"}},
            {"name": "løg", "quantity": "2",
             "source": {"suggestionTitle": "Chili con carne", "kind": "known"}},
            {"name": "kaffe", "quantity": "", "note": "the strong one"},
            {"name": "salt", "quantity": ""},
        ],
    )

    body = client.post("/api/shopping-list/export/reminders", json={}).json()

    assert body["items"] == [
        # Capitalised like a list item; the subtext is amount · what it's for.
        {"title": "Hakket oksekød", "notes": "1000 g · Chili con carne 500; Lasagne 500"},
        {"title": "Løg", "notes": "2 · Chili con carne"},
        {"title": "Kaffe", "notes": "the strong one"},
        {"title": "Salt", "notes": ""},
    ]


def test_reminders_export_can_send_just_the_selected_rows(client) -> None:
    _add(client, [{"name": "Milk", "quantity": "1 l"}, {"name": "Eggs", "quantity": "6"}])
    eggs = next(r for r in client.get("/api/shopping-list").json() if r["name"] == "Eggs")

    body = client.post(
        "/api/shopping-list/export/reminders", json={"lineIds": eggs["lineIds"]}
    ).json()

    assert body["items"] == [{"title": "Eggs", "notes": "6"}]



# --- Offers keep their shop; the list is grouped by shop ------------------------


def _offer(shop: str, slug: str | None, product: str, price: float | None = 20) -> dict:
    return {"shop": shop, "shopSlug": slug, "productName": product, "price": price}


def test_rows_keep_their_offer_and_are_grouped_by_shop(client) -> None:
    _add(
        client,
        [
            {"name": "salt"},
            {"name": "agurk", "offer": _offer("REMA 1000", "rema-1000", "Agurk", 6)},
            {"name": "hakket oksekød", "offer": _offer("Netto", "netto", "Hakket oksekød", 35)},
            {"name": "mælk"},
            {"name": "avocado", "offer": _offer("365discount", "coop-365", "Spisemodne avocadoer")},
            {"name": "bacon", "offer": _offer("Netto", "netto", "Brunchy bacon", 12.95)},
        ],
    )

    rows = client.get("/api/shopping-list").json()

    # The catalog's shop order (Netto, Rema 1000, … Coop 365), each shop's rows
    # in the order they were added, and what isn't on offer last.
    assert [r["name"] for r in rows] == [
        "hakket oksekød", "bacon", "agurk", "avocado", "salt", "mælk",
    ]
    assert rows[0]["offers"] == [_offer("Netto", "netto", "Hakket oksekød", 35)]
    assert rows[-1]["offers"] == []


def test_exports_carry_the_shop(client) -> None:
    _add(
        client,
        [
            {"name": "mælk", "quantity": "1 l"},
            {"name": "bacon", "quantity": "150 g", "offer": _offer("Netto", "netto", "Brunchy bacon", 12.95)},
        ],
    )

    text = client.get("/api/shopping-list/export.txt").text
    reminders = client.post("/api/shopping-list/export/reminders", json={}).json()["items"]

    # A heading per shop, the offer on the line, and the rest under "Other".
    assert "\nNetto\n[ ] bacon — 150 g · tilbud: Brunchy bacon, 12,95 kr\n" in text
    assert "\nOther\n[ ] mælk — 1 l\n" in text
    assert reminders == [
        {"title": "Bacon", "notes": "Netto: Brunchy bacon (12,95 kr) · 150 g"},
        {"title": "Mælk", "notes": "1 l"},
    ]


def test_exports_name_a_shop_by_its_chain_not_its_dealer(client) -> None:
    _add(client, [{"name": "avocado", "offer": _offer("365discount", "coop-365", "Avocado", 10)}])

    reminders = client.post("/api/shopping-list/export/reminders", json={}).json()["items"]

    assert reminders == [{"title": "Avocado", "notes": "Coop 365: Avocado (10 kr)"}]
    assert "\nCoop 365\n" in client.get("/api/shopping-list/export.txt").text
