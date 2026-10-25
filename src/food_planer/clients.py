"""External service clients: OpenAI (the planner LLM) and Tjek (discounts).

Both are network calls to third parties whose responses are non-deterministic
and, in OpenAI's case, billed. They are reached through the dependency
providers in :mod:`food_planer.app` so tests can swap in the fakes below via
``dependency_overrides`` (see ``spec.md`` → "Testing Decisions").

The real clients are thin: they make the network call and hand back the raw
payload. Everything worth testing happens on the far side of the seam.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMResult:
    """The outcome of one structured planning call.

    ``status`` mirrors the OpenAI Responses API outcomes the planner branches
    on: ``"completed"`` (usable output), ``"refused"`` (a safety refusal) and
    ``"incomplete"`` (the ``max_output_tokens`` ceiling was hit — truncated).
    The backend adds ``"error"`` when the call itself raised.
    """

    status: str
    output: dict[str, Any] | None = None
    # Set with status ``"error"``: the call raised (a timeout, an API outage).
    error: str | None = None


# How long one planning call may take before it's given up on, in seconds.
# The SDK's own default is 10 minutes per attempt plus 2 retries — long
# enough for a stalled request to look like a page that never loads. A full
# week normally comes back in 10–20 s.
OPENAI_TIMEOUT_SECONDS = float(os.environ.get("FOOD_PLANNER_OPENAI_TIMEOUT", "120"))


class OpenAIClient(Protocol):
    """The seam the planner talks to. One structured call in, one result out."""

    async def create_plan(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult: ...

    async def scan_fridge(
        self, *, prompt: str, images: list[tuple[str, bytes]], schema: dict[str, Any]
    ) -> LLMResult:
        """One vision call: ``images`` are ``(mime type, bytes)`` pairs."""
        ...

    async def review_matches(self, *, prompt: str, schema: dict[str, Any]) -> LLMResult:
        """One small text call: confirm or reject uncertain offer matches."""
        ...


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
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        from openai import AsyncOpenAI  # lazy: only the real path needs it

        from .planning import planning_json_schema, resolve_model

        # One retry covers a transient network blip without doubling a stall.
        client = AsyncOpenAI(timeout=OPENAI_TIMEOUT_SECONDS, max_retries=1)
        response = await client.responses.create(
            model=resolve_model(),
            input=prompt,
            max_output_tokens=max_output_tokens,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "weekly_plan",
                    "strict": True,
                    "schema": schema or planning_json_schema(),
                }
            },
        )
        return _structured_result(response)

    async def review_matches(self, *, prompt: str, schema: dict[str, Any]) -> LLMResult:
        from openai import AsyncOpenAI
        from .planning import resolve_model

        client = AsyncOpenAI(timeout=OPENAI_TIMEOUT_SECONDS, max_retries=1)
        response = await client.responses.create(
            model=resolve_model(),
            input=prompt,
            max_output_tokens=4000,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "match_review",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return _structured_result(response)

    async def scan_fridge(
        self, *, prompt: str, images: list[tuple[str, bytes]], schema: dict[str, Any]
    ) -> LLMResult:
        """Name what's in the fridge photos. The photos go inline as data URLs:
        they are looked at once and never kept, so there is nothing to upload
        to the Files API and clean up afterwards."""
        import base64

        from openai import AsyncOpenAI

        from .planning import resolve_model

        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for mime, data in images:
            encoded = base64.b64encode(data).decode("ascii")
            content.append(
                {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"}
            )
        client = AsyncOpenAI(timeout=OPENAI_TIMEOUT_SECONDS, max_retries=1)
        response = await client.responses.create(
            model=resolve_model(),
            input=[{"role": "user", "content": content}],
            max_output_tokens=4000,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "fridge_items",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return _structured_result(response)


def _structured_result(response: Any) -> LLMResult:
    """Map a Responses API reply onto an :class:`LLMResult`."""
    status = getattr(response, "status", "completed")
    if status == "incomplete":
        return LLMResult(status="incomplete")
    # A refusal surfaces as a refusal content part rather than plain text.
    for item in getattr(response, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            if getattr(part, "type", None) == "refusal":
                return LLMResult(status="refused")
    return LLMResult(status="completed", output=json.loads(response.output_text))


# The public v2 API behind etilbudsavis.dk. Unauthenticated today; see the ToS
# caveat in spec.md → "Discount sourcing" for why call volume stays tiny.
TJEK_API_BASE = "https://api.etilbudsavis.dk/v2"
# The API refuses a page larger than 100, and any page reaching past the
# 1000th row of a listing (offset + limit > 1000).
TJEK_PAGE_SIZE = 100
TJEK_MAX_ROWS = 1000


class RealTjekClient:
    """The Tjek/eTilbudsavis JSON client: raw dealer and offer payloads.

    Normalising and caching live in :mod:`food_planer.discounts`; this class
    only pages through the listing endpoints. A dealer's offers are listed one
    catalog at a time, because a big chain (Bilka: ~1200 offers over five
    catalogs) overflows the 1000-row ceiling of a single dealer-wide listing.
    """

    def __init__(self, base_url: str = TJEK_API_BASE, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    async def _list(
        self, client: Any, path: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for offset in range(0, TJEK_MAX_ROWS, TJEK_PAGE_SIZE):
            resp = await client.get(
                path, params={**params, "limit": TJEK_PAGE_SIZE, "offset": offset}
            )
            resp.raise_for_status()
            batch = resp.json()
            rows.extend(batch)
            if len(batch) < TJEK_PAGE_SIZE:
                break
        return rows

    def _client(self) -> Any:
        import httpx

        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def list_dealers(self) -> list[dict[str, Any]]:
        async with self._client() as client:
            return await self._list(client, "/dealers", {})

    async def list_offers(self, *, dealer_id: str) -> list[dict[str, Any]]:
        async with self._client() as client:
            catalogs = await self._list(client, "/catalogs", {"dealer_ids": dealer_id})
            offers: list[dict[str, Any]] = []
            for catalog in catalogs:
                batch = await self._list(
                    client, "/offers", {"catalog_ids": catalog["id"]}
                )
                # Carry the catalog's name ("Bilka Nonfood Uge 43 – …") on each
                # offer: it's the best food/non-food signal Tjek offers.
                for offer in batch:
                    offer["catalog_label"] = catalog.get("label")
                offers.extend(batch)
            return offers


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
    - ``"error"``     — raise, as a timeout or an API outage would.
    """

    behaviour: str = "success"
    canned: dict[str, Any] = field(default_factory=lambda: {"suggestions": []})
    calls: int = 0
    prompts: list[str] = field(default_factory=list)
    schemas: list[dict[str, Any] | None] = field(default_factory=list)
    # What a fridge scan returns, and the images each scan was sent.
    scan_output: dict[str, Any] = field(default_factory=lambda: {"items": []})
    scans: list[list[tuple[str, bytes]]] = field(default_factory=list)
    # What a match review returns; ``None`` approves every [m…] it was asked.
    review_output: dict[str, Any] | None = None
    reviews: list[str] = field(default_factory=list)

    async def create_plan(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        self.calls += 1
        # Record what the backend composed so prompt composition and the
        # schema are assertable through the seam without reaching inside.
        self.prompts.append(prompt)
        self.schemas.append(schema)
        if self.behaviour == "error":
            raise TimeoutError("Request timed out.")
        if self.behaviour == "refuse":
            return LLMResult(status="refused")
        if self.behaviour == "truncate_twice":
            return LLMResult(status="incomplete")
        if self.behaviour == "truncate_once":
            if self.calls == 1:
                return LLMResult(status="incomplete")
            return LLMResult(status="completed", output=self.canned)
        return LLMResult(status="completed", output=self.canned)


    async def scan_fridge(
        self, *, prompt: str, images: list[tuple[str, bytes]], schema: dict[str, Any]
    ) -> LLMResult:
        self.scans.append(images)
        if self.behaviour == "error":
            raise TimeoutError("Request timed out.")
        if self.behaviour == "refuse":
            return LLMResult(status="refused")
        return LLMResult(status="completed", output=self.scan_output)

    async def review_matches(self, *, prompt: str, schema: dict[str, Any]) -> LLMResult:
        self.reviews.append(prompt)
        if self.review_output is not None:
            return LLMResult(status="completed", output=self.review_output)
        ids = re.findall(r"\[(m\d+)\]", prompt)
        return LLMResult(
            status="completed", output={"verdicts": [{"id": i, "match": True} for i in ids]}
        )


@dataclass
class FakeTjekClient:
    """A stand-in returning canned dealer and offer payloads."""

    dealers: list[dict[str, Any]] = field(default_factory=list)
    offers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Set to make every call raise, as a Tjek outage would.
    fail: bool = False
    # Call counts, so caching is assertable through the seam.
    dealer_calls: int = 0
    offer_calls: int = 0

    async def list_dealers(self) -> list[dict[str, Any]]:
        self.dealer_calls += 1
        # Yield like a real network call, so concurrent fetches interleave.
        await asyncio.sleep(0)
        if self.fail:
            raise ConnectionError("Tjek is unreachable")
        return list(self.dealers)

    async def list_offers(self, *, dealer_id: str) -> list[dict[str, Any]]:
        self.offer_calls += 1
        await asyncio.sleep(0)
        if self.fail:
            raise ConnectionError("Tjek is unreachable")
        return list(self.offers.get(dealer_id, []))