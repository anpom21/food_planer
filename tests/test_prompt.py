"""The editable planning prompt: one household-wide template with {{variables}}.

- ``GET /api/prompt`` returns the template in force, the default, and the
  variables a template may use;
- ``PUT /api/prompt`` saves an edited template — and the next PlanningRun
  sends it, with each ``{{variable}}`` filled from the library and settings;
- a template naming an unknown variable is refused with a 422;
- ``template: null`` (or the default text verbatim) resets to the default;
- ``POST /api/prompt/preview`` renders a draft for a Profile, marking which
  pieces were injected, without saving or calling the model.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _make_profile(client: TestClient) -> str:
    resp = client.post(
        "/api/profiles/identify", json={"email": "ada@ex.com", "name": "Ada"}
    )
    return resp.json()["id"]


def test_prompt_starts_as_the_default_with_its_variables(client) -> None:
    body = client.get("/api/prompt").json()

    assert body["isDefault"] is True
    assert body["template"] == body["defaultTemplate"]
    assert "{{dish_library}}" in body["template"]
    names = {v["name"] for v in body["variables"]}
    assert {"days", "suggestions_per_day", "dish_library", "inspiration"} <= names
    assert all(v["description"] for v in body["variables"])


def test_saved_template_drives_the_next_run(client, fake_openai) -> None:
    fake_openai.canned = {"days": []}
    profile_id = _make_profile(client)
    client.post("/api/dishes", json={"title": "Frikadeller"})
    client.put(
        f"/api/profiles/{profile_id}/settings",
        json={"daysToPlan": 3, "inspiration": "more fish"},
    )

    resp = client.put(
        "/api/prompt",
        json={"template": "Plan {{days}} days. Wishes: {{ inspiration }}.\n{{dish_library}}"},
    )
    assert resp.status_code == 200
    assert resp.json()["isDefault"] is False

    client.post("/api/planning-runs", json={"profileId": profile_id})

    prompt = fake_openai.prompts[-1]
    assert prompt.startswith("Plan 3 days. Wishes: more fish.\n")
    assert "Frikadeller" in prompt
    assert "{{" not in prompt


def test_unknown_variable_is_refused_and_nothing_is_saved(client) -> None:
    resp = client.put("/api/prompt", json={"template": "Plan {{dayz}} days"})

    assert resp.status_code == 422
    assert "{{dayz}}" in resp.json()["detail"]
    assert client.get("/api/prompt").json()["isDefault"] is True


def test_null_or_default_text_resets_to_the_default(client) -> None:
    default = client.get("/api/prompt").json()["defaultTemplate"]

    client.put("/api/prompt", json={"template": "Plan {{days}} days"})
    assert client.put("/api/prompt", json={"template": None}).json()["isDefault"]

    client.put("/api/prompt", json={"template": "Plan {{days}} days"})
    assert client.put("/api/prompt", json={"template": default}).json()["isDefault"]


def test_line_holding_only_an_empty_variable_is_dropped(client, fake_openai) -> None:
    fake_openai.canned = {"days": []}
    profile_id = _make_profile(client)  # no Inspiration set
    client.put(
        "/api/prompt",
        json={"template": "Start.\n\n{{inspiration_instruction}}\n\nEnd."},
    )

    client.post("/api/planning-runs", json={"profileId": profile_id})

    assert fake_openai.prompts[-1] == "Start.\n\nEnd."


def test_preview_marks_injected_values_without_saving(client, fake_openai) -> None:
    profile_id = _make_profile(client)

    resp = client.post(
        "/api/prompt/preview",
        json={"profileId": profile_id, "template": "Plan {{days}} days."},
    )

    assert resp.status_code == 200
    assert resp.json()["segments"] == [
        {"text": "Plan ", "variable": None},
        {"text": "7", "variable": "days"},
        {"text": " days.", "variable": None},
    ]
    assert client.get("/api/prompt").json()["isDefault"] is True
    assert fake_openai.calls == 0


def test_preview_refuses_unknown_variables_and_unknown_profiles(client) -> None:
    profile_id = _make_profile(client)

    bad = client.post(
        "/api/prompt/preview", json={"profileId": profile_id, "template": "{{nope}}"}
    )
    missing = client.post("/api/prompt/preview", json={"profileId": "nobody"})

    assert bad.status_code == 422
    assert missing.status_code == 404


def test_saved_prompt_survives_a_restart(make_client, data_dir) -> None:
    first = make_client(data_dir)
    first.put("/api/prompt", json={"template": "Plan {{days}} days"})

    second = make_client(data_dir)

    assert second.get("/api/prompt").json()["template"] == "Plan {{days}} days"


def test_offer_limit_defaults_and_round_trips(client) -> None:
    body = client.get("/api/prompt").json()
    assert body["offerLimit"] == body["defaultOfferLimit"]

    saved = client.put(
        "/api/prompt", json={"template": None, "offerLimit": 250}
    ).json()
    assert saved["offerLimit"] == 250
    assert client.get("/api/prompt").json()["offerLimit"] == 250

    # Omitting it is a full replace back to the default, like the template.
    reset = client.put("/api/prompt", json={"template": None}).json()
    assert reset["offerLimit"] == reset["defaultOfferLimit"]


def test_offer_limit_is_bounded(client) -> None:
    ceiling = client.get("/api/prompt").json()["offerLimitCeiling"]

    assert client.put("/api/prompt", json={"offerLimit": -1}).status_code == 422
    assert (
        client.put("/api/prompt", json={"offerLimit": ceiling + 1}).status_code == 422
    )
