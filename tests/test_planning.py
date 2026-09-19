"""Plan a Week: one button, one pass, a board of day columns (issue #23).

Driven through the one seam — the HTTP API and the fake OpenAI client wired via
``dependency_overrides``. The fake returns canned structured responses and can
be told to refuse or to truncate, which is how ``success`` / ``partial`` /
``failed`` are exercised without spending money (spec.md → "Testing Decisions").
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _suggestion(title: str, source_dish: str | None) -> dict[str, Any]:
    """A full Suggestion in the LLM contract's shape (discounts denormalized)."""
    return {
        "title": title,
        "description": f"A tasty {title.lower()} for the evening.",
        "ingredients": [
            {"name": "onion", "quantity": "1"},
            {"name": "salt", "quantity": "1 pinch"},
        ],
        "estimatedCost": 55.0,
        "prepTimeMinutes": 30,
        "sourceDish": source_dish,
        "discounts": [],
    }


def _canned_week() -> dict[str, Any]:
    """Two days, two suggestions each, every dish distinct across the week."""
    return {
        "days": [
            {
                "day": 1,
                "suggestions": [
                    _suggestion("Frikadeller", "d1"),
                    _suggestion("Shakshuka", None),
                ],
            },
            {
                "day": 2,
                "suggestions": [
                    _suggestion("Pasta pesto", "d2"),
                    _suggestion("Bibimbap", None),
                ],
            },
        ]
    }


def _make_profile(client: TestClient, name: str = "Ada") -> str:
    resp = client.post(
        "/api/profiles/identify", json={"email": f"{name}@ex.com", "name": name}
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def _add_dish(client: TestClient, title: str, **fields: Any) -> str:
    resp = client.post("/api/dishes", json={"title": title, **fields})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_plan_a_week_returns_a_full_week_synchronously(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    profile_id = _make_profile(client)

    resp = client.post("/api/planning-runs", json={"profileId": profile_id})

    assert resp.status_code == 200
    run = resp.json()
    assert run["status"] == "success"
    assert run["profileId"] == profile_id
    assert len(run["days"]) == 2
    assert run["days"][0]["day"] == 1
    assert len(run["days"][0]["suggestions"]) == 2
    assert "id" in run and "createdAt" in run


def test_whole_week_is_a_single_call_with_no_repeated_dish(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    profile_id = _make_profile(client)

    run = client.post(
        "/api/planning-runs", json={"profileId": profile_id}
    ).json()

    # One press → exactly one LLM call, so the model can avoid cross-day repeats.
    assert fake_openai.calls == 1
    titles = [s["title"] for d in run["days"] for s in d["suggestions"]]
    assert len(titles) == len(set(titles))


def test_prompt_carries_dish_library_and_settings_as_prose(
    client, fake_openai
) -> None:
    fake_openai.canned = _canned_week()
    profile_id = _make_profile(client)
    _add_dish(client, "Grandma's lasagne", ingredients="pasta, beef")
    # Give the Profile some distinctive settings to look for in the prose.
    settings = client.get(f"/api/profiles/{profile_id}").json()["settings"]
    settings["inspiration"] = "something with aubergine"
    settings["priority"] = ["healthy", "cheap", "quick", "delicious"]
    client.put(f"/api/profiles/{profile_id}/settings", json=settings)

    client.post("/api/planning-runs", json={"profileId": profile_id})

    prompt = fake_openai.prompts[-1]
    assert "Grandma's lasagne" in prompt  # full library, verbatim
    assert "aubergine" in prompt  # Inspiration text
    assert "healthy" in prompt  # priority order rendered
    # Numbers appear as plain numbers, not a settings blob.
    assert "7" in prompt


def test_failed_run_returns_200_with_the_body_and_is_archived(
    client, fake_openai
) -> None:
    fake_openai.behaviour = "refuse"
    profile_id = _make_profile(client)

    resp = client.post("/api/planning-runs", json={"profileId": profile_id})

    # A safety refusal is a real persisted domain record, not a 5xx.
    assert resp.status_code == 200
    run = resp.json()
    assert run["status"] == "failed"
    assert run["days"] == []
    assert fake_openai.calls == 1  # no retry on a refusal

    archive = client.get("/api/planning-runs").json()
    assert any(r["id"] == run["id"] and r["status"] == "failed" for r in archive)


def test_truncation_retries_once_and_marks_partial(client, fake_openai) -> None:
    fake_openai.behaviour = "truncate_once"
    fake_openai.canned = _canned_week()
    profile_id = _make_profile(client)

    run = client.post(
        "/api/planning-runs", json={"profileId": profile_id}
    ).json()

    assert run["status"] == "partial"
    assert fake_openai.calls == 2  # one truncated call, one successful retry
    # The ask travels alongside the actuals so a short week can't read as full.
    assert run["requestedDays"] == 7
    assert run["requestedSuggestionsPerDay"] == 2


def test_truncation_twice_is_a_failure(client, fake_openai) -> None:
    fake_openai.behaviour = "truncate_twice"
    profile_id = _make_profile(client)

    run = client.post(
        "/api/planning-runs", json={"profileId": profile_id}
    ).json()

    assert run["status"] == "failed"
    assert run["days"] == []
    assert fake_openai.calls == 2  # exactly one retry, then give up


def test_settings_override_does_not_mutate_the_profile(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    profile_id = _make_profile(client)

    client.post(
        "/api/planning-runs",
        json={
            "profileId": profile_id,
            "settingsOverride": {
                "daysToPlan": 3,
                "suggestionsPerDay": 1,
                "knownVsUnknownBias": 0.9,
            },
        },
    )

    saved = client.get(f"/api/profiles/{profile_id}").json()["settings"]
    assert saved["daysToPlan"] == 7  # unchanged default
    assert saved["suggestionsPerDay"] == 2
    assert saved["knownVsUnknownBias"] == 0.5


def test_settings_override_drives_the_planned_prompt(client, fake_openai) -> None:
    # AC #4 (issue #25): a run with settingsOverride plans against the
    # overridden values, not the Profile's saved defaults.
    fake_openai.canned = _canned_week()
    profile_id = _make_profile(client)

    client.post(
        "/api/planning-runs",
        json={
            "profileId": profile_id,
            "settingsOverride": {
                "daysToPlan": 4,
                "suggestionsPerDay": 3,
                "knownVsUnknownBias": 0.9,
            },
        },
    )

    prompt = fake_openai.prompts[-1]
    # The default is 7 days × 2/day; the override's numbers are what got planned.
    assert "Plan exactly 4 day(s), with 3 dinner suggestion(s) per day." in prompt
    # bias 0.9 renders the "lean toward new dishes" prose, not the balanced one.
    assert "Lean toward new dishes" in prompt


def test_unknown_profile_is_a_404(client) -> None:
    resp = client.post("/api/planning-runs", json={"profileId": "nope"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Profile not found"


def test_run_persists_across_restart(make_client, data_dir, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    first = make_client(data_dir)
    profile_id = _make_profile(first)
    run = first.post(
        "/api/planning-runs", json={"profileId": profile_id}
    ).json()

    # Rebuild the app against the same data/ — the run is read back whole.
    second = make_client(data_dir)
    reloaded = second.get(f"/api/planning-runs/{run['id']}").json()
    assert reloaded["id"] == run["id"]
    assert len(reloaded["days"]) == 2


def test_structured_output_schema_is_strict_and_model_is_config(monkeypatch) -> None:
    """AC #4: strict JSON schema, model name from config.

    The schema and model live in the (untested-by-network) real client's
    request; these are the pure pieces the spec pins — every property required,
    optionality as a nullable union, and the model resolved from config.
    """
    from food_planer.planning import planning_json_schema, resolve_model

    schema = planning_json_schema()
    assert schema["type"] == "object"  # root is an object, not a bare array
    days = schema["properties"]["days"]
    assert days["type"] == "array"
    suggestion = days["items"]["properties"]["suggestions"]["items"]

    def assert_strict(obj: dict[str, Any]) -> None:
        if obj.get("type") == "object":
            assert obj["additionalProperties"] is False
            # strict mode: every property must appear in required
            assert set(obj["required"]) == set(obj["properties"])
            for child in obj["properties"].values():
                assert_strict(child)
        if obj.get("type") == "array":
            assert_strict(obj["items"])

    assert_strict(schema)
    # sourceDish is optional-as-nullable-union, not an omission.
    assert suggestion["properties"]["sourceDish"]["type"] == ["string", "null"]

    monkeypatch.setenv("FOOD_PLANNER_OPENAI_MODEL", "gpt-test-tiny")
    assert resolve_model() == "gpt-test-tiny"
    monkeypatch.delenv("FOOD_PLANNER_OPENAI_MODEL", raising=False)
    assert resolve_model()  # a non-empty default when unset


def test_details_carry_full_description_and_ingredients(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    profile_id = _make_profile(client)

    run = client.post(
        "/api/planning-runs", json={"profileId": profile_id}
    ).json()

    sugg = run["days"][0]["suggestions"][0]
    assert sugg["description"]
    assert sugg["ingredients"][0]["name"] == "onion"
    assert sugg["ingredients"][0]["quantity"] == "1"
