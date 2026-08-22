# Fridge images persist and are shown to the model directly

A FridgeImage used to be transient: uploaded, summarised into text by a separate LLM call, then discarded. We reversed that. A FridgeImage is now stored by the Household, downscaled on the way in, and included as image input on every PlanningRun alongside the rest of the planning context.

## Why

Summarising a fridge photo into text and throwing the photo away is lossy at exactly the moment fidelity matters: the model plans meals from what it can see, and a text summary is a second model's guess at what was in the picture. Passing the image directly removes that intermediate guess, and removes an entire LLM call from the flow.

## Considered options

- **Summarise once, discard the image** (the previous decision). Cheapest in tokens, and keeps nothing sensitive on disk — but every planning run afterwards works from a lossy summary, and the summary can't be re-derived once the image is gone.
- **Store the image, upload it per run.** Rejected: re-uploading the same photo on every run of the week is pure waste when the Files API will hold it.

## Consequences

- Image bytes now live on the Household's disk, so `data/` is no longer JSON-only.
- Images are uploaded once to OpenAI with `purpose: "vision"` and an `expires_after` window, and deleted there when removed locally. The local copy stays the source of truth, so a `file_id` that has expired or been deleted is silently re-uploaded rather than degrading the run.
- Images are downscaled on ingest, since they bill as tokens on every run they take part in and full phone resolution buys nothing for "what is in this fridge".
- A fridge photo can now go stale without the app knowing. Only a person can judge that, so removal stays manual and each image's age is shown.
