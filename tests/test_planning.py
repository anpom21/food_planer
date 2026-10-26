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


def _add_dish(client: TestClient, title: str, **fields: Any) -> str:
    resp = client.post("/api/dishes", json={"title": title, **fields})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_plan_a_week_returns_a_full_week_synchronously(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    # Ask for exactly what the canned week holds, so it's a full week.
    client.put(
        "/api/settings",
        json={"daysToPlan": 2, "suggestionsPerDay": 2},
    )

    resp = client.post("/api/planning-runs", json={})

    assert resp.status_code == 200
    run = resp.json()
    assert run["status"] == "success"
    assert "profileId" not in run and "profileName" not in run
    assert len(run["days"]) == 2
    assert run["days"][0]["day"] == 1
    assert len(run["days"][0]["suggestions"]) == 2
    assert "id" in run and "createdAt" in run


def test_whole_week_is_a_single_call_with_no_repeated_dish(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()

    run = client.post("/api/planning-runs", json={}).json()

    # One press → exactly one LLM call, so the model can avoid cross-day repeats.
    assert fake_openai.calls == 1
    titles = [s["title"] for d in run["days"] for s in d["suggestions"]]
    assert len(titles) == len(set(titles))


def test_prompt_carries_dish_library_and_settings_as_prose(
    client, fake_openai
) -> None:
    fake_openai.canned = _canned_week()
    _add_dish(client, "Grandma's lasagne", ingredients="pasta, beef")
    # Give the household some distinctive settings to look for in the prose.
    settings = client.get("/api/settings").json()
    settings["inspiration"] = "something with aubergine"
    settings["priority"] = ["healthy", "cheap", "quick", "delicious"]
    client.put("/api/settings", json=settings)

    client.post("/api/planning-runs", json={})

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

    resp = client.post("/api/planning-runs", json={})

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

    run = client.post("/api/planning-runs", json={}).json()

    assert run["status"] == "partial"
    assert fake_openai.calls == 2  # one truncated call, one successful retry
    # The ask travels alongside the actuals so a short week can't read as full.
    assert run["requestedDays"] == 7
    assert run["requestedSuggestionsPerDay"] == 2


def test_model_call_error_is_a_failed_run_not_a_500(
    client, fake_openai, data_dir
) -> None:
    import json

    fake_openai.behaviour = "error"

    resp = client.post("/api/planning-runs", json={})

    assert resp.status_code == 200
    run = resp.json()
    assert run["status"] == "failed"
    assert run["error"] == "TimeoutError: Request timed out."
    assert fake_openai.calls == 1  # the client already retried; no second pass
    # Persisted and traced, so a stalled call leaves evidence behind.
    assert client.get(f"/api/planning-runs/{run['id']}").json()["error"]
    trace = json.loads((data_dir / "run_logs" / f"{run['id']}.json").read_text("utf-8"))
    assert trace["calls"][0]["error"] == "TimeoutError: Request timed out."


def test_truncation_twice_is_a_failure(client, fake_openai) -> None:
    fake_openai.behaviour = "truncate_twice"

    run = client.post("/api/planning-runs", json={}).json()

    assert run["status"] == "failed"
    assert run["days"] == []
    assert fake_openai.calls == 2  # exactly one retry, then give up


def test_settings_override_does_not_mutate_the_saved_settings(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()

    client.post(
        "/api/planning-runs",
        json={
            "settingsOverride": {
                "daysToPlan": 3,
                "suggestionsPerDay": 1,
                "knownVsUnknownBias": 0.9,
            },
        },
    )

    saved = client.get("/api/settings").json()
    assert saved["daysToPlan"] == 7  # unchanged default
    assert saved["suggestionsPerDay"] == 2
    assert saved["knownVsUnknownBias"] == 0.5


def test_settings_override_drives_the_planned_prompt(client, fake_openai) -> None:
    # AC #4 (issue #25): a run with settingsOverride plans against the
    # overridden values, not the household's saved defaults.
    fake_openai.canned = _canned_week()

    client.post(
        "/api/planning-runs",
        json={
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


def test_run_persists_across_restart(make_client, data_dir, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    first = make_client(data_dir)
    run = first.post("/api/planning-runs", json={}).json()

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
    assert "minItems" not in days  # unpinned without a run's numbers
    # sourceDish is optional-as-nullable-union, not an omission.
    assert suggestion["properties"]["sourceDish"]["type"] == ["string", "null"]

    monkeypatch.setenv("FOOD_PLANNER_OPENAI_MODEL", "gpt-test-tiny")
    assert resolve_model() == "gpt-test-tiny"
    monkeypatch.delenv("FOOD_PLANNER_OPENAI_MODEL", raising=False)
    assert resolve_model()  # a non-empty default when unset


def test_schema_pins_the_requested_day_and_suggestion_counts(
    client, fake_openai
) -> None:
    fake_openai.canned = _canned_week()
    client.put(
        "/api/settings",
        json={"daysToPlan": 5, "suggestionsPerDay": 3},
    )

    client.post("/api/planning-runs", json={})

    days = fake_openai.schemas[-1]["properties"]["days"]
    assert days["minItems"] == days["maxItems"] == 5
    suggestions = days["items"]["properties"]["suggestions"]
    assert suggestions["minItems"] == suggestions["maxItems"] == 3


def test_truncation_retry_schema_pins_the_halved_counts(client, fake_openai) -> None:
    fake_openai.behaviour = "truncate_once"
    fake_openai.canned = _canned_week()
    # Household settings are the defaults: 7 days x 2.

    client.post("/api/planning-runs", json={})

    retry_days = fake_openai.schemas[-1]["properties"]["days"]
    assert retry_days["minItems"] == retry_days["maxItems"] == 3
    suggestions = retry_days["items"]["properties"]["suggestions"]
    assert suggestions["minItems"] == suggestions["maxItems"] == 1


def test_short_week_from_the_model_is_partial_not_success(
    client, fake_openai
) -> None:
    fake_openai.canned = _canned_week()  # two days
    client.put(
        "/api/settings",
        json={"daysToPlan": 5, "suggestionsPerDay": 2},
    )

    run = client.post("/api/planning-runs", json={}).json()

    assert run["status"] == "partial"
    assert run["dayCount"] == 2
    assert run["requestedDays"] == 5
    assert run["requestedSuggestionsPerDay"] == 2
    assert fake_openai.calls == 1  # flagged, not retried


def test_too_few_suggestions_on_a_day_is_partial(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()  # two suggestions a day
    client.put(
        "/api/settings",
        json={"daysToPlan": 2, "suggestionsPerDay": 3},
    )

    run = client.post("/api/planning-runs", json={}).json()

    assert run["status"] == "partial"


# --- Past plans archive (issue #26) ---------------------------------------
# Every run stays browsable forever, household-wide, newest first, as summaries — no suggestions shipped just to draw a list.


def test_archive_lists_every_run_newest_first(client, fake_openai) -> None:
    # Two runs are made; the archive lists both, the most recent first.
    fake_openai.canned = _canned_week()

    first = client.post("/api/planning-runs", json={}).json()
    second = client.post("/api/planning-runs", json={}).json()

    archive = client.get("/api/planning-runs").json()
    ids = [r["id"] for r in archive]
    assert set(ids) == {first["id"], second["id"]}
    # Newest first: the later run leads the list.
    assert ids[0] == second["id"]
    assert ids[1] == first["id"]


def test_archive_rows_are_summaries_not_full_runs(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()
    client.post("/api/planning-runs", json={})

    row = client.get("/api/planning-runs").json()[0]
    # The list ships the summary fields the archive draws from…
    for field in ("id", "createdAt", "dayCount", "status"):
        assert field in row
    assert "profileName" not in row  # runs belong to the household, not a person
    assert "fridgeSnippet" in row
    # …but never the suggestion payload — that is the {id} read's job.
    assert "days" not in row


def test_archive_prunes_nothing(client, fake_openai) -> None:
    # An old run is still listed after many later runs — nothing is pruned.
    fake_openai.canned = _canned_week()
    oldest = client.post("/api/planning-runs", json={}).json()

    for _ in range(12):
        client.post("/api/planning-runs", json={})

    archive = client.get("/api/planning-runs").json()
    assert len(archive) == 13
    assert any(r["id"] == oldest["id"] for r in archive)


def test_details_carry_full_description_and_ingredients(client, fake_openai) -> None:
    fake_openai.canned = _canned_week()

    run = client.post("/api/planning-runs", json={}).json()

    sugg = run["days"][0]["suggestions"][0]
    assert sugg["description"]
    assert sugg["ingredients"][0]["name"] == "onion"
    assert sugg["ingredients"][0]["quantity"] == "1"
