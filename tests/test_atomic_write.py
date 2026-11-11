"""The atomic write-through never leaves a truncated JSON file.

This pins the acceptance criterion directly on the store, since a crash mid-
write is not reachable through the HTTP seam. The write goes to a temp file and
is swapped in with ``os.replace``; a failure before the swap must leave the
previous good file (or no file) intact — never a half-written one.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from food_planer.store import JsonFile


def run(coro):
    return asyncio.run(coro)


def test_failed_write_leaves_previous_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "dishes.json"
    jf = JsonFile(path, default=[])

    run(jf.update(lambda d: d.append({"id": "1", "title": "Lasagne"})))
    good = path.read_text(encoding="utf-8")

    # Simulate the process dying while serialising the next write.
    def boom(_data):
        raise KeyboardInterrupt("killed mid-write")

    with pytest.raises(KeyboardInterrupt):
        run(jf.update(boom))

    # The file on disk is still the last good, fully-valid JSON.
    assert path.read_text(encoding="utf-8") == good
    assert json.loads(path.read_text(encoding="utf-8")) == [
        {"id": "1", "title": "Lasagne"}
    ]
    # No stray temp files were left behind.
    assert list(tmp_path.glob("*.tmp")) == []


def test_no_truncated_file_when_serialisation_fails(tmp_path: Path) -> None:
    path = tmp_path / "dishes.json"
    jf = JsonFile(path, default=[])

    # A value json can't serialise makes the dump fail after the temp file is
    # opened — the real file must never appear truncated.
    with pytest.raises(TypeError):
        run(jf.update(lambda d: d.append({"bad": object()})))

    assert not path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
