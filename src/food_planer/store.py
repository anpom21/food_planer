"""JSON persistence layer.

One JSON file per entity type under a ``data/`` directory. Each file is loaded
into an in-memory cache at startup, guarded by its own :class:`asyncio.Lock`,
and written back atomically (temp file + ``os.replace``) so a killed process can
never leave a truncated JSON file behind. See ``spec.md`` → "Data storage
layout".
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def new_id() -> str:
    """A backend-generated entity id: a UUID4 as a hex string."""
    return uuid.uuid4().hex


# One entry per entity type. Collections default to ``[]``; singletons to their
# empty object. This is the whole on-disk schema of the app.
ENTITY_DEFAULTS: dict[str, Any] = {
    # The household's planning settings (one set, no profiles).
    "settings": {},
    "dishes": [],
    "planning_runs": [],
    "fridge_context": {"text": "", "images": []},
    # What is in the house: fresh items and pantry staples, plus every name
    # added before so the common-items list learns the household's habits.
    "fridge": {"items": [], "history": []},
    "shopping_list": {"items": []},
    # My week: the dishes chosen per week, each a Suggestion snapshot filed
    # under the Monday of its week. Old weeks stay, to look back through.
    "my_week": {"entries": []},
    # The household's edited planning prompt and how many offers it carries;
    # null means the built-in default for either.
    "prompt": {"template": None, "offerLimit": None},
    # Which model the planner runs on and its credentials (Settings → Model):
    # the provider ("openai" / "claude-code"), each one's model, an OpenAI API
    # key and a Claude Code token. null means the default / the environment.
    "model": {},
    # How the household has personalised the app: its name, mark and accent
    # colour (Settings → Personalize). Empty means the app's own look.
    "appearance": {},
}


class JsonFile:
    """A single JSON file with an in-memory cache, a lock and atomic writes."""

    def __init__(self, path: Path, default: Any) -> None:
        self.path = path
        self._default = default
        self._lock = asyncio.Lock()
        self._cache = self._load_from_disk()

    def _load_from_disk(self) -> Any:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        return copy.deepcopy(self._default)

    def ensure_persisted(self) -> None:
        """Write the current cache to disk if the file does not exist yet.

        Lets the :class:`Store` lay down the full data layout on first run so
        ``data/`` holds one JSON file per entity type from the start, not only
        once a write happens to touch it. The bare :class:`JsonFile` primitive
        stays lazy; this is a deliberate, one-off materialisation step.
        """
        if not self.path.exists():
            self._atomic_write(self._cache)

    def seed(self, data: Any) -> None:
        """Replace the contents synchronously, for startup migrations that run
        before any request (so the lock isn't needed). Atomic like ``update``."""
        self._atomic_write(data)
        self._cache = copy.deepcopy(data)

    def read(self) -> Any:
        """Return a deep copy of the cached contents.

        Reads hit the cache directly; the copy stops callers mutating cached
        state without going through :meth:`update`.
        """
        return copy.deepcopy(self._cache)

    async def update(self, mutate: Callable[[Any], T]) -> T:
        """Mutate the contents under the file's lock and persist atomically.

        ``mutate`` receives a mutable copy of the current contents and may
        return a value (e.g. the record it just created), which is returned to
        the caller. The cache is only advanced once the write to disk has
        succeeded, so a failed write leaves both disk and cache unchanged.
        """
        async with self._lock:
            working = copy.deepcopy(self._cache)
            result = mutate(working)
            self._atomic_write(working)
            self._cache = working
            return result

    def _atomic_write(self, data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            # Leave the real file untouched; drop the half-written temp file.
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise


class Store:
    """The collection of JSON files that make up one household's state."""

    def __init__(
        self,
        data_dir: str | os.PathLike[str],
        shared_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        # data_dir is one household's (a user's); shared_dir holds what every
        # household reads alike — imported recipes and shop logos. A store on
        # its own (no users) keeps both in one place.
        self.data_dir = Path(data_dir)
        self.shared_dir = Path(shared_dir) if shared_dir is not None else self.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # data/ is no longer JSON-only: it also holds image binaries (ADR 0002).
        (self.data_dir / "fridge_images").mkdir(exist_ok=True)
        (self.shared_dir / "icons").mkdir(parents=True, exist_ok=True)
        self._files: dict[str, JsonFile] = {
            name: JsonFile(self.data_dir / f"{name}.json", default)
            for name, default in ENTITY_DEFAULTS.items()
        }
        # Lay down one JSON file per entity type on first run, so the on-disk
        # layout is complete and self-evident before any write happens.
        for jf in self._files.values():
            jf.ensure_persisted()

    def __getitem__(self, name: str) -> JsonFile:
        return self._files[name]
