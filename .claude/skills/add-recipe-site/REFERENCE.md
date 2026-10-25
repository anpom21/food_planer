# Recipe site adapter reference

## Adapter template

```python
"""example.dk — one line on the site.

Discovery: how the index lists recipes and when it stops.
Parsing: JSON-LD / microdata, and what ``refine`` adds.
"""

from __future__ import annotations

from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from ..model import Ingredient, Recipe, RecipeRef
from ..schema_org import SchemaRecipe, clean_text
from .base import SchemaOrgSite

BASE_URL = "https://www.example.dk"


class Example(SchemaOrgSite):
    name = "example"  # the CLI argument and the JSON file name

    def discover(self, http: httpx.Client) -> Iterator[RecipeRef]:
        page = 1
        while True:
            resp = http.get(f"{BASE_URL}/opskrifter/", params={"page": page})
            resp.raise_for_status()
            items = resp.json()["items"]
            for item in items:
                yield RecipeRef(
                    url=item["url"],
                    title=clean_text(item["title"]) or item["url"],
                    thumbnail=item.get("image"),
                    source_id=str(item["id"]),
                )
            if not items:  # use the site's own stop rule
                return
            page += 1

    def refine(self, recipe: Recipe, soup: BeautifulSoup, schema: SchemaRecipe) -> Recipe:
        # Only what the generic parse misses. Example: ingredient sub-headings.
        return recipe
```

Register it in `sites/__init__.py`:

```python
SITES: dict[str, SiteAdapter] = {site.name: site for site in (Valdemarsro(), Example())}
```

## Discovery recipes

**Sitemap** (when there is no load-more endpoint):

```python
import re
xml = http.get(f"{BASE_URL}/recipe-sitemap.xml").text
for url in re.findall(r"<loc>(.*?)</loc>", xml):
    yield RecipeRef(url=url, title="")  # title "" → taken from the page
```

A sitemap has no thumbnails; `parse` falls back to the page's schema.org
image. If the sitemap mixes articles with recipes, filter by URL pattern, or
let `parse` return `None` (no ingredients) so they land in `skipped`.

**Paginated HTML**: parse each `/page/N/` with BeautifulSoup, stop when a page
yields no URL you haven't seen.

## What the generic parse gives you

`SchemaOrgSite.parse` fills `title, thumbnail, image, description,
ingredients (no groups), instructions, servings, total_time, work_time,
categories, keywords, author, published`. The index's title and thumbnail win
over the page's. Returns `None` when there is no recipe or no ingredients.

## Gotchas seen so far

- valdemarsro has **no Recipe JSON-LD** (only an Article); it uses microdata.
  Don't assume JSON-LD — the probe tells you.
- Microdata nests other items (author, publisher) inside the recipe scope; the
  parser skips properties of nested `itemscope`s, so `name` is the recipe's.
- Ingredient sub-headings ("Til servering") are rarely in schema.org data;
  read them from the visible list in `refine` (see `sites/valdemarsro.py`).
- Times in schema.org are ISO 8601 (`PT30M`); prefer the page's
  human-readable stat row in `refine` when there is one.
- Text often holds `&nbsp;` — always pass through `clean_text`.
- A load-more endpoint may accept a huge page size; still page like the site
  does, so the count matches what clicking the button would load.
