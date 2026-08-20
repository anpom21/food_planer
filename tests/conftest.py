"""Shared test fixtures — the pattern every later test starts from.

There is one seam: the HTTP API, driven by a FastAPI ``TestClient``. Four
fixtures are established here (see ``spec.md`` → "Testing Decisions"):

- ``data_dir``    — a function-scoped temp ``data/`` (real disk, empty household)
- ``fake_openai`` — a scriptable fake OpenAI client
- ``fake_tjek``   — a fake Tjek client returning canned payloads
- ``client``      — a ``TestClient`` with both fakes wired via
  ``dependency_overrides``

Later tests should be able to start from these and add nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from food_planer.app import create_app, get_openai_client, get_tjek_client
from food_planer.clients import FakeOpenAIClient, FakeTjekClient


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A fresh, empty ``data/`` directory for one test."""
    return tmp_path / "data"


@pytest.fixture
def fake_openai() -> FakeOpenAIClient:
    return FakeOpenAIClient()


@pytest.fixture
def fake_tjek() -> FakeTjekClient:
    return FakeTjekClient()


@pytest.fixture
def make_client(
    fake_openai: FakeOpenAIClient, fake_tjek: FakeTjekClient
):
    """Build a ``TestClient`` bound to a given ``data/`` directory.

    Exposed so a test can rebuild a second app against the same directory to
    prove state survives a restart.
    """

    clients: list[TestClient] = []

    def _make(directory: Path) -> TestClient:
        app = create_app(
            data_dir=directory,
            openai_client=fake_openai,
            tjek_client=fake_tjek,
        )
        app.dependency_overrides[get_openai_client] = lambda: fake_openai
        app.dependency_overrides[get_tjek_client] = lambda: fake_tjek
        tc = TestClient(app)
        clients.append(tc)
        return tc

    yield _make

    for tc in clients:
        tc.close()


@pytest.fixture
def client(make_client, data_dir: Path) -> Iterator[TestClient]:
    """A ready-to-use ``TestClient`` against a temp ``data/``."""
    yield make_client(data_dir)
