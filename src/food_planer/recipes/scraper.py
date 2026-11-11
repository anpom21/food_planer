"""Fetch every recipe from a site and store them as one local JSON file.

``data/recipes/<site>.json`` holds::

    {
      "source": "valdemarsro",
      "updated_at": "2026-10-25T12:00:00+00:00",
      "count": 1787,
      "recipes": [ {Recipe}, ... ],          # in the site's own index order
      "skipped": [ {"url", "title", "reason"}, ... ]
    }

``skipped`` lists index entries that turned out not to be recipes (or failed to
fetch), so a re-run doesn't fetch them again. A re-run only fetches URLs not
yet in the file, unless ``refresh`` is set; the file is checkpointed as it goes,
so an interrupted scrape resumes where it stopped.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from .model import Recipe, RecipeRef
from .sites import SiteAdapter

USER_AGENT = "food-planer recipe importer (personal, non-commercial)"
CHECKPOINT_EVERY = 50
RETRIES = 3


def recipes_dir(data_dir: str | os.PathLike[str]) -> Path:
    return Path(data_dir) / "recipes"


def write_json_atomic(path: Path, data: Any) -> None:
    """Temp file + ``os.replace``, so a killed scrape never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_site_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"recipes": [], "skipped": []}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch(http: httpx.Client, url: str, delay: float) -> str:
    for attempt in range(RETRIES):
        try:
            time.sleep(delay)
            resp = http.get(url)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def scrape(
    site: SiteAdapter,
    data_dir: str | os.PathLike[str],
    *,
    workers: int = 4,
    delay: float = 0.25,
    limit: int | None = None,
    refresh: bool = False,
    http: httpx.Client | None = None,
    log: Callable[[str], None] = print,
) -> Path:
    out = recipes_dir(data_dir) / f"{site.name}.json"
    http = http or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    )

    refs = list({ref.url: ref for ref in site.discover(http)}.values())
    log(f"{site.name}: found {len(refs)} recipes in the index")
    if limit is not None:
        refs = refs[:limit]

    existing = {} if refresh else load_site_file(out)
    done: dict[str, dict] = {r["url"]: r for r in existing.get("recipes", [])}
    skipped: dict[str, dict] = {s["url"]: s for s in existing.get("skipped", [])}
    todo = [ref for ref in refs if ref.url not in done and ref.url not in skipped]
    log(f"{site.name}: {len(done)} already stored, {len(todo)} to fetch")

    def save() -> None:
        order = {ref.url: i for i, ref in enumerate(refs)}
        recipes = sorted(done.values(), key=lambda r: order.get(r["url"], len(order)))
        write_json_atomic(
            out,
            {
                "source": site.name,
                "updated_at": _now(),
                "count": len(recipes),
                "recipes": recipes,
                "skipped": list(skipped.values()),
            },
        )

    def work(ref: RecipeRef) -> tuple[RecipeRef, Recipe | None, str | None]:
        try:
            return ref, site.parse(_fetch(http, ref.url, delay), ref), None
        except Exception as exc:  # one bad page must not sink the whole scrape
            return ref, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, ref) for ref in todo]
        for n, future in enumerate(as_completed(futures), 1):
            ref, recipe, error = future.result()
            if recipe is not None:
                recipe.scraped_at = _now()
                done[ref.url] = recipe.to_dict()
            else:
                reason = error or "no recipe on page"
                skipped[ref.url] = {"url": ref.url, "title": ref.title, "reason": reason}
                log(f"  skipped {ref.url}: {reason}")
            if n % CHECKPOINT_EVERY == 0:
                save()
                log(f"  {n}/{len(todo)} fetched")

    save()
    log(f"{site.name}: stored {len(done)} recipes ({len(skipped)} skipped) in {out}")
    return out
