"""The fake clients honour the contract later tests depend on.

The planning endpoints that consume these land in a later ticket; here we pin
the four OpenAI behaviours the status machine needs, and that both fakes are
wired onto the app via ``dependency_overrides``.
"""

from __future__ import annotations

import asyncio

from food_planer.app import get_openai_client, get_tjek_client
from food_planer.clients import FakeOpenAIClient, FakeTjekClient


def run(coro):
    return asyncio.run(coro)


def test_fake_openai_success() -> None:
    fake = FakeOpenAIClient(behaviour="success", canned={"suggestions": [1]})
    result = run(fake.create_plan(prompt="p", max_output_tokens=100))
    assert result.status == "completed"
    assert result.output == {"suggestions": [1]}


def test_fake_openai_refuse() -> None:
    fake = FakeOpenAIClient(behaviour="refuse")
    result = run(fake.create_plan(prompt="p", max_output_tokens=100))
    assert result.status == "refused"
    assert result.output is None


def test_fake_openai_truncate_once_then_succeeds() -> None:
    fake = FakeOpenAIClient(behaviour="truncate_once", canned={"ok": True})
    first = run(fake.create_plan(prompt="p", max_output_tokens=100))
    second = run(fake.create_plan(prompt="p", max_output_tokens=50))
    assert first.status == "incomplete"
    assert second.status == "completed"
    assert second.output == {"ok": True}


def test_fake_openai_truncate_twice() -> None:
    fake = FakeOpenAIClient(behaviour="truncate_twice")
    first = run(fake.create_plan(prompt="p", max_output_tokens=100))
    second = run(fake.create_plan(prompt="p", max_output_tokens=50))
    assert first.status == "incomplete"
    assert second.status == "incomplete"


def test_fake_tjek_returns_canned_payloads() -> None:
    fake = FakeTjekClient(
        dealers=[{"id": "d1", "name": "Netto"}],
        offers={"d1": [{"heading": "Mælk"}]},
    )
    assert run(fake.list_dealers()) == [{"id": "d1", "name": "Netto"}]
    assert run(fake.list_offers(dealer_id="d1")) == [{"heading": "Mælk"}]
    assert run(fake.list_offers(dealer_id="missing")) == []


def test_fakes_are_wired_via_dependency_overrides(client) -> None:
    app = client.app
    assert get_openai_client in app.dependency_overrides
    assert get_tjek_client in app.dependency_overrides
