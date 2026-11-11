"""Settings → Model: which LLM the planner runs on, through the HTTP seam.

- ``GET /api/model`` defaults to OpenAI with no key saved;
- ``PUT /api/model`` saves the provider and models; a secret sent as null is
  kept, as "" is removed, and is never echoed back — only whether one is set
  and an OpenAI key's last four characters;
- the settings persist to ``data/model.json`` and survive a restart;
- the real client routes each call to the provider saved at call time;
- a Claude Code run's result message maps onto the planner's statuses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from food_planer.clients import (
    DEFAULT_CLAUDE_MODEL,
    ClaudeCodeClient,
    ConfiguredLLMClient,
    RealOpenAIClient,
)


def test_defaults_to_openai_with_no_key_saved(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = client.get("/api/model").json()
    assert body["provider"] == "openai"
    assert body["openaiKeySet"] is False
    assert body["openaiKeyFromEnv"] is False
    assert body["claudeTokenSet"] is False
    assert body["defaultClaudeModel"] == DEFAULT_CLAUDE_MODEL


def test_saves_provider_and_secrets_without_echoing_them(client, household_dir: Path):
    body = client.put(
        "/api/model",
        json={
            "provider": "claude-code",
            "claudeModel": "claude-sonnet-5-5",
            "openaiApiKey": "sk-test-abcd1234",
            "claudeToken": "sk-ant-oat-secret",
        },
    ).json()
    assert body["provider"] == "claude-code"
    assert body["claudeModel"] == "claude-sonnet-5-5"
    assert body["openaiKeySet"] and body["openaiKeyHint"] == "1234"
    assert body["claudeTokenSet"]
    assert "sk-test-abcd1234" not in json.dumps(body)
    assert "sk-ant-oat-secret" not in json.dumps(body)

    stored = json.loads((household_dir / "model.json").read_text("utf-8"))
    assert stored["openaiApiKey"] == "sk-test-abcd1234"
    assert stored["claudeToken"] == "sk-ant-oat-secret"


def test_null_keeps_a_secret_and_empty_removes_it(client):
    client.put("/api/model", json={"openaiApiKey": "sk-keep", "claudeToken": "tok"})
    body = client.put(
        "/api/model", json={"provider": "openai", "claudeToken": ""}
    ).json()
    assert body["openaiKeySet"] is True
    assert body["claudeTokenSet"] is False


def test_model_settings_survive_a_restart(make_client, data_dir: Path):
    make_client(data_dir).put(
        "/api/model", json={"provider": "claude-code", "openaiModel": "gpt-5-mini"}
    )
    body = make_client(data_dir).get("/api/model").json()
    assert body["provider"] == "claude-code"
    assert body["openaiModel"] == "gpt-5-mini"


def test_routes_to_the_provider_saved_at_call_time():
    config: dict[str, Any] = {"openaiApiKey": "sk-x", "openaiModel": "gpt-5-mini"}
    router = ConfiguredLLMClient(lambda: config)

    chosen = router._client()
    assert isinstance(chosen, RealOpenAIClient)
    assert (chosen.api_key, chosen.model) == ("sk-x", "gpt-5-mini")

    config.update(provider="claude-code", claudeToken="tok")
    chosen = router._client()
    assert isinstance(chosen, ClaudeCodeClient)
    assert (chosen.model, chosen.oauth_token) == (DEFAULT_CLAUDE_MODEL, "tok")


@pytest.mark.parametrize(
    ("result", "status"),
    [
        ({"subtype": "success", "structured_output": {"items": []}}, "completed"),
        ({"subtype": "success", "stop_reason": "refusal"}, "refused"),
        ({"subtype": "success", "stop_reason": "max_tokens"}, "incomplete"),
        ({"subtype": "error_max_structured_output_retries", "is_error": True}, "error"),
    ],
)
def test_claude_code_result_maps_onto_planner_statuses(monkeypatch, result, status):
    import asyncio

    import claude_agent_sdk
    from claude_agent_sdk import ResultMessage

    seen: dict[str, Any] = {}

    async def fake_query(*, prompt, options):
        seen["options"] = options
        yield ResultMessage(
            **{
                "subtype": "success",
                "duration_ms": 1,
                "duration_api_ms": 1,
                "is_error": False,
                "num_turns": 1,
                "session_id": "s",
                **result,
            }
        )

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    outcome = asyncio.run(
        ClaudeCodeClient(oauth_token="tok").review_matches(prompt="p", schema={})
    )
    assert outcome.status == status
    options = seen["options"]
    assert options.tools == [] and options.setting_sources == []
    assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"
    assert options.env["ANTHROPIC_API_KEY"] == ""


def test_claude_status_reports_a_saved_token_without_running_the_cli(client):
    client.put("/api/model", json={"claudeToken": "tok"})
    body = client.get("/api/model/claude-status").json()
    assert body["loggedIn"] is True and body["authMethod"] == "token"


def test_claude_status_when_claude_code_is_not_installed(client, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    body = client.get("/api/model/claude-status").json()
    assert body == {"installed": False, "loggedIn": False}
