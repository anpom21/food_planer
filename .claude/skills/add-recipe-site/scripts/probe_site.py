"""Probe a recipe website before writing an adapter for it.

    uv run python .claude/skills/add-recipe-site/scripts/probe_site.py <index-url> <recipe-url>

Reports, for the recipe page: whether it carries a schema.org Recipe as JSON-LD
or microdata, and what the generic parser extracts from it. For the index page:
sitemaps, "load more" style AJAX endpoints in inline scripts, and pagination
links — the discovery options, best first.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from food_planer.recipes.model import RecipeRef
from food_planer.recipes.schema_org import _from_json_ld, _from_microdata
from food_planer.recipes.scraper import USER_AGENT
from food_planer.recipes.sites.base import SchemaOrgSite


def probe_recipe(http: httpx.Client, url: str) -> None:
    print(f"== Recipe page: {url}")
    html = http.get(url).text
    soup = BeautifulSoup(html, "html.parser")
    json_ld, micro = _from_json_ld(soup), _from_microdata(soup)
    print(f"JSON-LD Recipe:   {'yes' if json_ld else 'no'}")
    print(f"Microdata Recipe: {'yes' if micro else 'no'}")
    if not (json_ld or micro):
        print("No schema.org Recipe: parse() must be written by hand (override it).")
        lists = soup.select("[class*=ingredient]")
        print(f"Elements with 'ingredient' in their class: {len(lists)}")
        for el in lists[:5]:
            print(f"  <{el.name} class={el.get('class')}>")
        return

    class Probe(SchemaOrgSite):
        name = "probe"

    recipe = Probe().parse(html, RecipeRef(url=url, title=""))
    if recipe is None:
        print("Generic parse found a Recipe but no ingredients.")
        return
    data = recipe.to_dict()
    data["description"] = (data["description"] or "")[:160]
    data["ingredients"] = [i["text"] for i in data["ingredients"]]
    print("Generic parse result:")
    print(json.dumps(data, ensure_ascii=False, indent=1))


def probe_index(http: httpx.Client, url: str) -> None:
    print(f"\n== Index page: {url}")
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for path in ("/sitemap_index.xml", "/sitemap.xml", "/robots.txt"):
        resp = http.get(origin + path)
        if resp.status_code == 200:
            found = re.findall(r"(?:<loc>|Sitemap:\s*)(\S+?)(?:</loc>|\s|$)", resp.text)
            print(f"{path}: {len(found)} entries")
            for loc in found[:15]:
                print(f"  {loc}")

    html = http.get(url).text
    soup = BeautifulSoup(html, "html.parser")
    scripts = "\n".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))
    ajax = set(re.findall(r"""(?:url\s*:\s*|fetch\(\s*)['"]([^'"]+)['"]""", scripts))
    print(f"AJAX URLs in inline scripts: {sorted(ajax) or 'none'}")
    buttons = [
        a for a in soup.find_all(["a", "button"])
        if re.search(r"flere|more|load|indlæs|næste|next", a.get_text(" ", strip=True), re.I)
    ]
    for b in buttons[:8]:
        print(f"  button: {b.get_text(' ', strip=True)!r} href={b.get('href')} onclick={b.get('onclick')}")
    pages = {urljoin(url, a["href"]) for a in soup.find_all("a", href=True) if re.search(r"/page/\d+|[?&]page=\d+", a["href"])}
    print(f"Pagination links: {sorted(pages)[:5] or 'none'}")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    index_url, recipe_url = sys.argv[1:]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as http:
        probe_recipe(http, recipe_url)
        probe_index(http, index_url)


if __name__ == "__main__":
    main()
