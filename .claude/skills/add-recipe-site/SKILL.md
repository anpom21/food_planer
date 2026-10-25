---
name: add-recipe-site
description: Adds a new recipe website to the food planner's recipe importer (src/food_planer/recipes), so its recipes are scraped into data/recipes/<site>.json and shown on the Recipes screen and to the planner. Use when the user wants to import, scrape or support recipes from another website (e.g. arla.dk, madbanditten.dk, a URL to a recipe index), or when an existing site adapter breaks.
---

# Add a recipe website

A site is one **adapter** in `src/food_planer/recipes/sites/` with two jobs:
`discover` (list every recipe: url, title, thumbnail) and `parse` (one recipe
page → `Recipe`). `SchemaOrgSite` already parses schema.org JSON-LD and
microdata, so most sites only need `discover`, plus `refine` for extras.

## Workflow

- [ ] 1. **Probe the site** (run from the repo root):
  `uv run python .claude/skills/add-recipe-site/scripts/probe_site.py <index-url> <one-recipe-url>`
  It reports the recipe data on the page (JSON-LD / microdata / none), what the
  generic parser extracts, and discovery options (sitemaps, load-more
  endpoints, `/page/N/` links).
- [ ] 2. **Choose discovery**, in this order of preference:
  1. The index's own "load more" JSON endpoint (find it in the page's inline
     JS — `ajax`, `fetch(`, `page=`). Stop on the same rule the button uses.
  2. A recipe sitemap (`/sitemap_index.xml`, `/recipe-sitemap.xml`).
  3. Paginated HTML (`/page/2/`), stopping when a page adds no new URLs.
  Never stop early: the user wants *all* recipes. Compare your count with the
  site's own total if it shows one.
- [ ] 3. **Write the adapter** from the template in [REFERENCE.md](REFERENCE.md):
  subclass `SchemaOrgSite`, set `name`, implement `discover`; override
  `refine` only for what the generic parse misses (ingredient sub-headings,
  human-readable times, site-only facts → `recipe.extra`).
- [ ] 4. **Register it** in `sites/__init__.py` (`SITES`).
- [ ] 5. **Test offline** — add a test to `tests/test_recipes.py` with a trimmed
  copy of a real page and an `httpx.MockTransport` index (see the valdemarsro
  tests there). Cover: discovery stop rule, ingredients (with groups),
  instructions, thumbnail. `uv run pytest -q`.
- [ ] 6. **Trial run**: `uv run food-planer-recipes <name> --limit 5 --data-dir <scratch dir>`
  and read the JSON. Check ingredients are clean lines, instructions are
  steps, the thumbnail URL loads.
- [ ] 7. **Full run**: `uv run food-planer-recipes <name>` (in the background;
  ~1 s per recipe at 4 workers). Then check coverage — every stored recipe
  should have `thumbnail`, `ingredients`, `instructions` — and read the
  `skipped` list: each entry should genuinely not be a recipe.
- [ ] 8. **Dinner category**: the planner only uses recipes whose
  `categories` include one of `DINNER_CATEGORIES` in
  `recipes/matching.py`. If the site labels dinners differently, add its label.
- [ ] 9. **Ingredient names**: the planner matches fridge items and offers on
  `ingredient_name(line)`. Sample 40 lines and check the names; for a
  non-Danish site extend `ITEM_TERMS`, `_UNITS`, `_DESCRIPTIVE`, `_TRAILING`.

## Rules

- Be polite: keep the scraper's defaults (4 workers, 0.25 s delay, retries).
- The stored shape is the shared `Recipe` dataclass (`recipes/model.py`);
  don't add site-specific fields to it — use `extra`.
- A page with no ingredients is skipped, not an error. A crash on one page
  must not stop the scrape (the scraper already isolates pages).
- `data/` is gitignored: the JSON is local only.
