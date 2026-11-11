"""The registry of supported recipe websites, keyed by adapter name."""

from __future__ import annotations

from .base import SchemaOrgSite, SiteAdapter
from .valdemarsro import Valdemarsro

SITES: dict[str, SiteAdapter] = {site.name: site for site in (Valdemarsro(),)}

__all__ = ["SITES", "SchemaOrgSite", "SiteAdapter"]
