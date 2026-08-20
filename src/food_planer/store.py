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
    "profiles": [],
    "dishes": [],
    "planning_runs": [],
    "fridge_context": {"text": "", "images": []},
    "shopping_list": {"items": []},
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
    """The collection of JSON files that make up the household's state."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # data/ is no longer JSON-only: it also holds image binaries (ADR 0002).
        (self.data_dir / "fridge_images").mkdir(exist_ok=True)
        (self.data_dir / "icons").mkdir(exist_ok=True)
        self._files: dict[str, JsonFile] = {
            name: JsonFile(self.data_dir / f"{name}.json", default)
            for name, default in ENTITY_DEFAULTS.items()
        }

    def __getitem__(self, name: str) -> JsonFile:
        return self._files[name]
