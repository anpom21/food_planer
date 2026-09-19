"""External service clients: OpenAI (the planner LLM) and Tjek (discounts).

Both are network calls to third parties whose responses are non-deterministic
and, in OpenAI's case, billed. They are reached through the dependency
providers in :mod:`food_planer.app` so tests can swap in the fakes below via
``dependency_overrides`` (see ``spec.md`` → "Testing Decisions").

The real clients are thin placeholders here: the walking skeleton establishes
the seam and the fakes; the planning pipeline that drives them lands in a later
ticket.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMResult:
    """The outcome of one structured planning call.

    ``status`` mirrors the OpenAI Responses API outcomes the planner branches
    on: ``"completed"`` (usable output), ``"refused"`` (a safety refusal) and
    ``"incomplete"`` (the ``max_output_tokens`` ceiling was hit — truncated).
    """

    status: str
    output: dict[str, Any] | None = None


class OpenAIClient(Protocol):
    """The seam the planner talks to. One structured call in, one result out."""

    async def create_plan(
        self, *, prompt: str, max_output_tokens: int
    ) -> LLMResult: ...


class TjekClient(Protocol):
    """The seam the discount pipeline talks to."""

    async def list_dealers(self) -> list[dict[str, Any]]: ...

    async def list_offers(self, *, dealer_id: str) -> list[dict[str, Any]]: ...


class RealOpenAIClient:
    """The hardcoded OpenAI planner (issue #23).

    One structured call per PlanningRun via the Responses API with
    ``text.format`` set to a strict ``json_schema``; the model name comes from
    config (:func:`food_planer.planning.resolve_model`). The SDK is imported
    lazily so the app — and every test, which swaps in the fake — never needs
    the ``openai`` package installed.
    """

    async def create_plan(
        self, *, prompt: str, max_output_tokens: int
    ) -> LLMResult:
        from openai import AsyncOpenAI  # lazy: only the real path needs it

        from .planning import planning_json_schema, resolve_model

        client = AsyncOpenAI()
        response = await client.responses.create(
            model=resolve_model(),
            input=prompt,
            max_output_tokens=max_output_tokens,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "weekly_plan",
                    "strict": True,
                    "schema": planning_json_schema(),
                }
            },
        )
        status = getattr(response, "status", "completed")
        if status == "incomplete":
            return LLMResult(status="incomplete")
        # A refusal surfaces as a refusal content part rather than plain text.
        for item in getattr(response, "output", []) or []:
            for part in getattr(item, "content", []) or []:
                if getattr(part, "type", None) == "refusal":
                    return LLMResult(status="refused")
        return LLMResult(
            status="completed", output=json.loads(response.output_text)
        )


class RealTjekClient:
    """Placeholder for the Tjek/eTilbudsavis client (built in a later ticket)."""

    async def list_dealers(self) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "The Tjek discount pipeline is not part of the walking skeleton."
        )

    async def list_offers(self, *, dealer_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "The Tjek discount pipeline is not part of the walking skeleton."
        )


# --- Fakes, wired into tests via dependency_overrides -----------------------


@dataclass
class FakeOpenAIClient:
    """A scriptable stand-in for the planner LLM.

    ``behaviour`` selects one of the four cases the status machine needs to
    exercise ``success`` / ``partial`` / ``failed`` without spending money:

    - ``"success"``   — return the canned plan immediately.
    - ``"refuse"``    — a safety refusal on the first call, no retry.
    - ``"truncate_once"`` — truncate the first call, succeed on the retry.
    - ``"truncate_twice"`` — truncate every call (the retry fails too).
    """

    behaviour: str = "success"
    canned: dict[str, Any] = field(default_factory=lambda: {"suggestions": []})
    calls: int = 0
    prompts: list[str] = field(default_factory=list)

    async def create_plan(
        self, *, prompt: str, max_output_tokens: int
    ) -> LLMResult:
        self.calls += 1
        # Record what the backend composed so prompt composition is assertable
        # through the seam without reaching into internals.
        self.prompts.append(prompt)
        if self.behaviour == "refuse":
            return LLMResult(status="refused")
        if self.behaviour == "truncate_twice":
            return LLMResult(status="incomplete")
        if self.behaviour == "truncate_once":
            if self.calls == 1:
                return LLMResult(status="incomplete")
            return LLMResult(status="completed", output=self.canned)
        return LLMResult(status="completed", output=self.canned)


@dataclass
class FakeTjekClient:
    """A stand-in returning canned dealer and offer payloads."""

    dealers: list[dict[str, Any]] = field(default_factory=list)
    offers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def list_dealers(self) -> list[dict[str, Any]]:
        return list(self.dealers)

    async def list_offers(self, *, dealer_id: str) -> list[dict[str, Any]]:
        return list(self.offers.get(dealer_id, []))
