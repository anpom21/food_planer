"""Food Planner backend package."""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Loaded on import so OPENAI_API_KEY (read implicitly by AsyncOpenAI() in
# clients.py) is set before any request reaches the real OpenAI client.
load_dotenv()

from .app import create_app

__all__ = ["create_app", "main"]


def main() -> None:
    """Run the FastAPI app with a single Uvicorn worker.

    A single worker is a hard requirement: the persistence layer keeps its
    state in one in-memory cache per file, so a second worker would see stale
    data. See ``spec.md`` → "Concurrency".
    """
    import logging

    import uvicorn

    # The app's own loggers (planning runs, tilbudsavis fetches) at INFO by
    # default; FOOD_PLANNER_LOG_LEVEL=DEBUG adds cache hits, WARNING quietens.
    logging.basicConfig(
        level=os.environ.get("FOOD_PLANNER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # One line per HTTP request (a Bilka fetch is ~20) would drown the
    # planning log; failures still surface as WARNING and above.
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    host = os.environ.get("FOOD_PLANNER_HOST", "0.0.0.0")
    port = int(os.environ.get("FOOD_PLANNER_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, workers=1)
