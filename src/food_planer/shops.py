"""The fixed catalog of Danish grocery chains — backend-owned (issue #20).

The chain list lives server-side because the discount pipeline resolves each
preferred shop to a Tjek dealer id by name anyway, so the canonical slug↔chain
mapping exists here either way; duplicating it in the frontend would create two
lists that must agree (see ``spec.md`` → "Shops"). The frontend renders the
pills and the coloured-initial fallback, but the names and slugs come from here.
"""

from __future__ import annotations

import re
from pathlib import Path

# The Danish chains the app knows, in display order. Hand-curated to the chains
# a household actually uses that Tjek carries; picking one of these means the
# discount fetcher can name-match it to a dealer without exact spelling.
DANISH_CHAINS: list[str] = [
    "Netto",
    "Rema 1000",
    "Føtex",
    "Bilka",
    "Lidl",
    "Aldi",
    "Coop 365",
    "SuperBrugsen",
    "Irma",
    "Meny",
]

# Extensions tried when resolving data/icons/<slug>.<ext>, in preference order.
ICON_EXTENSIONS: tuple[str, ...] = ("svg", "png", "webp", "jpg", "jpeg")

# A well-formed slug: the only shape slugify() produces. Used to reject a
# path-traversal slug before it ever touches the filesystem.
_SAFE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def slugify(name: str) -> str:
    """Chain name → slug: lowercase, æ/ø/å stripped, every other run of
    non-alphanumerics collapsed to a single hyphen, edges trimmed.

    Stripping (not transliterating) æ/ø/å is the spec's rule; the frontend
    derives the same slug from the same name, so the two never disagree.
    """
    s = name.lower()
    s = s.replace("æ", "").replace("ø", "").replace("å", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def icon_path(icons_dir: Path, slug: str) -> Path | None:
    """The on-disk icon file for a slug, or ``None`` when no file exists yet.

    A slug that is not a well-formed slug (e.g. one carrying ``/`` or ``..`` to
    climb out of ``data/icons/``) resolves to ``None`` rather than a real file.
    """
    if not _SAFE_SLUG.fullmatch(slug):
        return None
    for ext in ICON_EXTENSIONS:
        candidate = icons_dir / f"{slug}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def shop_catalog(icons_dir: Path) -> list[dict]:
    """The catalog rows: ``{slug, name, hasIcon}`` for every known chain.

    ``hasIcon`` is resolved against ``icons_dir`` at call time so dropping a new
    logo file in needs no restart — and lets the frontend choose the fallback
    badge without a failed image request per pill.
    """
    rows: list[dict] = []
    for name in DANISH_CHAINS:
        slug = slugify(name)
        rows.append(
            {
                "slug": slug,
                "name": name,
                "hasIcon": icon_path(icons_dir, slug) is not None,
            }
        )
    return rows
