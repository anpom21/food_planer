"""External service clients: the planner LLM (OpenAI, or Claude through Claude
Code) and Tjek (discounts).

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
from typing import Any, Callable, Protocol


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
# Claude Code starts a CLI process and the default model thinks before it
# answers, so a week takes longer than on gpt-4o-mini.
CLAUDE_TIMEOUT_SECONDS = float(os.environ.get("FOOD_PLANNER_CLAUDE_TIMEOUT", "300"))


class OpenAIClient(Protocol):
    """The seam the planner talks to. One structured call in, one result out.

    Named for the first provider; :class:`ConfiguredLLMClient` is the real
    implementation and routes each call to OpenAI or Claude Code."""

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

    async def fetch_image(self, url: str) -> tuple[bytes, str]:
        """An image Tjek links to (a dealer's logo): its bytes and media type."""
        ...


class RealOpenAIClient:
    """The hardcoded OpenAI planner (issue #23).

    One structured call per PlanningRun via the Responses API with
    ``text.format`` set to a strict ``json_schema``; the model name comes from
    config (:func:`food_planer.planning.resolve_model`). The SDK is imported
    lazily so the app — and every test, which swaps in the fake — never needs
    the ``openai`` package installed.

    ``api_key`` and ``model`` come from the household's model settings; left
    unset, the SDK reads ``OPENAI_API_KEY`` and the model comes from config.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model

    def _client(self) -> Any:
        from openai import AsyncOpenAI  # lazy: only the real path needs it

        # One retry covers a transient network blip without doubling a stall.
        return AsyncOpenAI(
            api_key=self.api_key, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=1
        )

    def _model(self) -> str:
        from .planning import resolve_model

        return self.model or resolve_model()

    async def create_plan(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        from .planning import planning_json_schema

        response = await self._client().responses.create(
            model=self._model(),
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
        response = await self._client().responses.create(
            model=self._model(),
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

        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for mime, data in images:
            encoded = base64.b64encode(data).decode("ascii")
            content.append(
                {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"}
            )
        response = await self._client().responses.create(
            model=self._model(),
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


# The model Claude Code runs unless the household picks another.
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"


class ClaudeCodeClient:
    """Claude through the local Claude Code install (the Agent SDK), so calls
    run on the household's Claude Pro/Max subscription rather than API billing.

    Auth is Claude Code's own: the ``claude auth login`` of whoever runs the
    app, or a long-lived ``claude setup-token`` token when one is given. Each
    call is one tool-less session whose answer comes back through the SDK's
    structured output, validated against the same schema the OpenAI path uses.
    The SDK is imported lazily, like the OpenAI one.
    """

    def __init__(self, model: str | None = None, oauth_token: str | None = None) -> None:
        self.model = model or DEFAULT_CLAUDE_MODEL
        self.oauth_token = oauth_token

    async def _run(self, prompt: Any, schema: dict[str, Any]) -> LLMResult:
        import tempfile

        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        # An ANTHROPIC_API_KEY in the app's environment would win over the
        # subscription login and bill the API instead; blank it for this call.
        env = {"ANTHROPIC_API_KEY": ""}
        if self.oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token
        options = ClaudeAgentOptions(
            model=self.model,
            # No built-in tools and none of the user's Claude Code settings,
            # hooks or CLAUDE.md files: the call is a plain question, and the
            # StructuredOutput tool the SDK adds is the only one it can use.
            tools=[],
            setting_sources=[],
            max_turns=4,
            system_prompt="Answer through the structured output tool only.",
            cwd=tempfile.gettempdir(),
            env=env,
            output_format={"type": "json_schema", "schema": schema},
        )
        result: ResultMessage | None = None

        async def collect() -> None:
            nonlocal result
            try:
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, ResultMessage):
                        result = message
            except Exception:
                # A failed run yields its result and then raises; the result
                # says more than the exception, so keep it when there is one.
                if result is None:
                    raise

        await asyncio.wait_for(collect(), timeout=CLAUDE_TIMEOUT_SECONDS)
        if result is None:
            return LLMResult(status="error", error="Claude Code returned no result")
        if result.stop_reason == "max_tokens":
            return LLMResult(status="incomplete")
        if result.stop_reason == "refusal":
            return LLMResult(status="refused")
        if result.subtype == "success" and result.structured_output is not None:
            return LLMResult(status="completed", output=result.structured_output)
        detail = "; ".join(result.errors or []) or result.result or result.subtype
        return LLMResult(status="error", error=f"Claude Code: {detail}")

    async def create_plan(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        from .planning import planning_json_schema

        return await self._run(prompt, schema or planning_json_schema())

    async def review_matches(self, *, prompt: str, schema: dict[str, Any]) -> LLMResult:
        return await self._run(prompt, schema)

    async def scan_fridge(
        self, *, prompt: str, images: list[tuple[str, bytes]], schema: dict[str, Any]
    ) -> LLMResult:
        """The photos go inline as base64 image blocks in one streamed user
        message, never written to disk."""
        import base64

        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
            for mime, data in images
        ]
        content.append({"type": "text", "text": prompt})

        async def message():
            yield {"type": "user", "message": {"role": "user", "content": content}}

        return await self._run(message(), schema)


async def claude_code_status(oauth_token: str | None = None) -> dict[str, Any]:
    """What ``claude auth status`` reports: whether Claude Code is signed in,
    how, and on which plan. ``installed`` is False when there is no ``claude``
    on the PATH. A token from ``claude setup-token`` isn't checked here (only a
    real call proves it), so it is reported as given."""
    import shutil

    if oauth_token:
        return {"installed": True, "loggedIn": True, "authMethod": "token"}
    cli = shutil.which("claude")
    if cli is None:
        return {"installed": False, "loggedIn": False}
    proc = await asyncio.create_subprocess_exec(
        cli, "auth", "status", "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    try:
        status = json.loads(out)
    except ValueError:
        return {"installed": True, "loggedIn": False}
    return {
        "installed": True,
        "loggedIn": bool(status.get("loggedIn")),
        "authMethod": status.get("authMethod"),
        "email": status.get("email"),
        "subscriptionType": status.get("subscriptionType"),
    }


class ConfiguredLLMClient:
    """The real planner client: routes each call to the provider the
    household picked in Settings → Model. ``config`` returns the stored model
    settings (``data/model.json``) and is read per call, so a change applies to
    the next call without a restart.

    ``machine_credentials`` says whether the household may fall back on the
    server's own ``OPENAI_API_KEY`` and Claude Code login when it has saved no
    key or token of its own — true only for the server's owner, so other users
    never spend the owner's API money or subscription."""

    def __init__(
        self, config: Callable[[], dict[str, Any]], machine_credentials: bool = True
    ) -> None:
        self.config = config
        self.machine_credentials = machine_credentials

    def _client(self) -> OpenAIClient:
        cfg = self.config()
        if cfg.get("provider") == "claude-code":
            if not cfg.get("claudeToken") and not self.machine_credentials:
                raise PermissionError(
                    "Add your own Claude Code token under Settings → Model"
                )
            return ClaudeCodeClient(cfg.get("claudeModel"), cfg.get("claudeToken"))
        if not cfg.get("openaiApiKey") and not self.machine_credentials:
            raise PermissionError("Add your own OpenAI API key under Settings → Model")
        return RealOpenAIClient(cfg.get("openaiApiKey"), cfg.get("openaiModel"))

    async def create_plan(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        return await self._client().create_plan(
            prompt=prompt, max_output_tokens=max_output_tokens, schema=schema
        )

    async def scan_fridge(
        self, *, prompt: str, images: list[tuple[str, bytes]], schema: dict[str, Any]
    ) -> LLMResult:
        return await self._client().scan_fridge(prompt=prompt, images=images, schema=schema)

    async def review_matches(self, *, prompt: str, schema: dict[str, Any]) -> LLMResult:
        return await self._client().review_matches(prompt=prompt, schema=schema)


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

    async def fetch_image(self, url: str) -> tuple[bytes, str]:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type", "")

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
    # Images by URL, as ``(bytes, media type)``; any other URL fails.
    images: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    # Call counts, so caching is assertable through the seam.
    dealer_calls: int = 0
    offer_calls: int = 0
    image_calls: int = 0

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

    async def fetch_image(self, url: str) -> tuple[bytes, str]:
        self.image_calls += 1
        await asyncio.sleep(0)
        if self.fail or url not in self.images:
            raise ConnectionError(f"no image at {url}")
        return self.images[url]