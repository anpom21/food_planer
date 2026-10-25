"""Importing recipes from recipe websites into ``data/recipes/<site>.json``.

- the generic parse reads a schema.org Recipe from JSON-LD or from microdata;
- the valdemarsro adapter adds ingredient sub-headings and the stat row;
- discovery pages through the "Vis flere opskrifter" endpoint until a short page;
- a scrape stores every recipe, records non-recipe pages as skipped, and a
  re-run fetches only what isn't stored yet;
- ``GET /api/recipes`` serves the stored recipes, or ``[]`` before any import.

No test touches the network: the site is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from food_planer.recipes import RecipeRef, scrape
from food_planer.recipes.sites.base import SchemaOrgSite
from food_planer.recipes.sites.valdemarsro import PAGE_SIZE, Valdemarsro

# A trimmed valdemarsro recipe page: microdata only, no Recipe JSON-LD.
VALDEMARSRO_PAGE = """
<html><head>
<meta property="article:published_time" content="2026-10-23T10:05:48+00:00" />
</head><body itemscope itemtype="http://schema.org/WebPage">
<div class="main-wrapper single-post" itemscope itemtype="http://schema.org/Recipe">
  <span itemprop="publisher" itemscope itemtype="https://schema.org/Organization">
    <span itemprop="name">Valdemarsro</span>
  </span>
  <span itemprop="author" itemscope itemtype="https://schema.org/Person">
    <span itemprop="name">Ann-Christine</span>
  </span>
  <span itemprop="recipeCategory">Aftensmad</span>
  <span itemprop="keywords">Suppe, Vegetar</span>
  <img src="https://example.test/porresuppe.jpg" itemprop="image"/>
  <div itemprop="description" id="recipe-intro"><p>Lækker suppe.</p><p>Og nem.</p></div>
  <h2 itemprop="name">Porresuppe</h2>
  <div class="recipe-stats">
    <div class="recipe-stat"><span class="recipe-stat-label">Tid i alt</span><strong>30 min.</strong></div>
    <div class="recipe-stat"><span class="recipe-stat-label">Kan fryses</span><strong>Ja</strong></div>
    <div class="recipe-stat"><span class="recipe-stat-label">Antal</span><strong>4 pers. <i></i></strong></div>
  </div>
  <ul class="ingredientlist content">
    <li itemprop="recipeIngredient">500 g porre, i ringe</li>
    <li itemprop="recipeIngredient">1&nbsp;liter bouillon</li>
    <li class="ingredient-header">Til servering</li>
    <li itemprop="recipeIngredient">4 skiver rugbrød</li>
  </ul>
  <div itemprop="recipeInstructions" class="content"><p>Sauter porre.</p><p>Blend suppen.</p></div>
</div></body></html>
"""

JSON_LD_PAGE = """
<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "name": "ignored"},
  {"@type": ["Recipe"], "name": "Pandekager", "image": ["https://example.test/p.jpg"],
   "recipeIngredient": ["3 æg", "5 dl mælk"],
   "recipeInstructions": [
     {"@type": "HowToSection", "name": "Dej", "itemListElement": [
       {"@type": "HowToStep", "text": "Pisk æg og mælk."}]},
     {"@type": "HowToStep", "text": "Steg pandekagerne."}],
   "recipeYield": ["4"], "totalTime": "PT30M", "recipeCategory": "Dessert",
   "author": {"@type": "Person", "name": "Kok"}}
]}
</script></head><body></body></html>
"""

ARTICLE_PAGE = "<html><body><h1>Sådan rister du nødder</h1><p>Ingen opskrift her.</p></body></html>"


class JsonLdSite(SchemaOrgSite):
    """A stand-in for some other website: nothing site-specific at all."""

    name = "other"


def test_valdemarsro_page_parses_from_microdata() -> None:
    ref = RecipeRef(url="https://v.test/porresuppe/", title="Porresuppe", thumbnail="https://v.test/t.jpg", source_id="1")
    recipe = Valdemarsro().parse(VALDEMARSRO_PAGE, ref)

    assert recipe is not None
    assert recipe.title == "Porresuppe"
    assert recipe.thumbnail == "https://v.test/t.jpg"  # the index thumbnail wins
    assert recipe.image == "https://example.test/porresuppe.jpg"
    assert [(i.text, i.group) for i in recipe.ingredients] == [
        ("500 g porre, i ringe", None),
        ("1 liter bouillon", None),  # non-breaking space normalised
        ("4 skiver rugbrød", "Til servering"),
    ]
    assert recipe.instructions == ["Sauter porre.", "Blend suppen."]
    assert recipe.description == "Lækker suppe.\n\nOg nem."
    assert recipe.total_time == "30 min."
    assert recipe.servings == "4 pers."
    assert recipe.extra == {"Kan fryses": "Ja"}
    assert recipe.categories == ["Aftensmad", "Suppe", "Vegetar"]
    # The author's name, not the publisher's (both are nested itemscopes).
    assert recipe.author == "Ann-Christine"
    assert recipe.published == "2026-10-23T10:05:48+00:00"


def test_generic_parse_reads_json_ld_with_sections() -> None:
    recipe = JsonLdSite().parse(JSON_LD_PAGE, RecipeRef(url="https://o.test/p", title=""))

    assert recipe is not None
    assert recipe.source == "other"
    assert recipe.title == "Pandekager"  # falls back to the page's own name
    assert recipe.thumbnail == "https://example.test/p.jpg"  # no index thumbnail → page image
    assert [i.text for i in recipe.ingredients] == ["3 æg", "5 dl mælk"]
    assert recipe.instructions == ["Pisk æg og mælk.", "Steg pandekagerne."]
    assert recipe.servings == "4"
    assert recipe.categories == ["Dessert"]
    assert recipe.author == "Kok"


def test_page_without_a_recipe_parses_to_none() -> None:
    assert JsonLdSite().parse(ARTICLE_PAGE, RecipeRef(url="https://o.test/a", title="a")) is None


def _index_item(n: int) -> dict:
    return {"title": f"Ret {n}", "id": n, "url": f"https://v.test/ret-{n}/", "img_url": f"https://v.test/{n}.jpg"}


def _valdemarsro_transport(total: int, pages: dict[str, str] | None = None, log: list[str] | None = None):
    """Serves the load-more endpoint for ``total`` recipes, plus recipe pages."""

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(str(request.url))
        if request.url.path == "/opskrifter/":
            page = int(request.url.params["ajaxpage"])
            start = (page - 1) * PAGE_SIZE
            items = [_index_item(n) for n in range(start, min(start + PAGE_SIZE, total))]
            return httpx.Response(200, json={"success": True, "data": items})
        if pages is not None and str(request.url) in pages:
            return httpx.Response(200, text=pages[str(request.url)])
        return httpx.Response(200, text=VALDEMARSRO_PAGE)

    return httpx.MockTransport(handler)


def test_discover_follows_load_more_until_a_short_page() -> None:
    requested: list[str] = []
    http = httpx.Client(transport=_valdemarsro_transport(2 * PAGE_SIZE + 5, log=requested))

    refs = list(Valdemarsro().discover(http))

    assert len(refs) == 2 * PAGE_SIZE + 5
    assert len(requested) == 3  # 60 + 60 + 5, then the button would hide
    assert refs[0] == RecipeRef(url="https://v.test/ret-0/", title="Ret 0", thumbnail="https://v.test/0.jpg", source_id="0")


def test_discover_asks_once_more_when_the_last_page_is_exactly_full() -> None:
    requested: list[str] = []
    http = httpx.Client(transport=_valdemarsro_transport(PAGE_SIZE, log=requested))

    assert len(list(Valdemarsro().discover(http))) == PAGE_SIZE
    assert len(requested) == 2  # a full page, then an empty one


def test_scrape_stores_recipes_skips_articles_and_resumes(tmp_path: Path) -> None:
    pages = {"https://v.test/ret-1/": ARTICLE_PAGE}
    requested: list[str] = []
    http = httpx.Client(transport=_valdemarsro_transport(3, pages, requested))

    out = scrape(Valdemarsro(), tmp_path, delay=0, http=http, log=lambda _: None)

    stored = json.loads(out.read_text(encoding="utf-8"))
    assert out == tmp_path / "recipes" / "valdemarsro.json"
    assert stored["source"] == "valdemarsro"
    assert stored["count"] == 2
    # Kept in the site's index order, each with its own index title/thumbnail.
    assert [r["url"] for r in stored["recipes"]] == ["https://v.test/ret-0/", "https://v.test/ret-2/"]
    assert stored["recipes"][1]["thumbnail"] == "https://v.test/2.jpg"
    assert stored["recipes"][0]["ingredients"][0] == {"text": "500 g porre, i ringe", "group": None}
    assert stored["skipped"] == [{"url": "https://v.test/ret-1/", "title": "Ret 1", "reason": "no recipe on page"}]

    # A re-run fetches only the index: everything is stored or known-skipped.
    requested.clear()
    scrape(Valdemarsro(), tmp_path, delay=0, http=http, log=lambda _: None)
    assert all("/opskrifter/" in url for url in requested)


def test_api_lists_no_recipes_before_any_import(client) -> None:
    assert client.get("/api/recipes").json() == []


def test_api_lists_imported_recipes(client, data_dir: Path) -> None:
    http = httpx.Client(transport=_valdemarsro_transport(2))
    scrape(Valdemarsro(), data_dir, delay=0, http=http, log=lambda _: None)

    recipes = client.get("/api/recipes").json()

    assert [r["title"] for r in recipes] == ["Ret 0", "Ret 1"]
    card = recipes[0]
    assert card["ingredients"][2] == {
        "text": "4 skiver rugbrød", "group": "Til servering",
        "name": "rugbrød", "quantity": "4 skiver", "have": None,
    }
    # Shaped like a Suggestion card: a rough price (nothing in the house, no
    # offers without a profile: 3 items × 20 kr), counts and the recipe link.
    assert card["estimatedCost"] == 60
    assert card["counts"] == {"fresh": 0, "staple": 0, "offers": 0}
    assert card["prepTimeMinutes"] == 30
    assert card["description"] == "Lækker suppe."
    assert card["recipe"]["url"] == "https://v.test/ret-0/"
