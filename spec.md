# Food Planner — Specification

Synthesis of the decisions accumulated across the [Food Planner — Spec Map](https://github.com/anpom21/food_planer/issues/1) (#2–#10). Domain vocabulary is defined in [`CONTEXT.md`](CONTEXT.md); architecture reversals are recorded in `docs/adr/`.

Three map tickets are still open at the time of writing — [#11](https://github.com/anpom21/food_planer/issues/11) (discount fetch failure handling), [#12](https://github.com/anpom21/food_planer/issues/12) (dev/run setup and deployment topology) and [#13](https://github.com/anpom21/food_planer/issues/13) (LLM cost controls). This spec deliberately covers everything that *is* settled so a first version can be built and judged; the three open areas are named as open questions under **Further Notes** rather than answered by guesswork.

## Problem Statement

Deciding what to eat for the week is a recurring chore that costs more effort than it should. The person doing it is holding several things in their head at once: what's already in the fridge and going off, which meals the household actually likes and can cook without looking anything up, whether they're in the mood for something familiar or something new, how much time each evening realistically allows, and which ingredients happen to be on offer this week at the shops they use. Balancing all of that by hand is slow, so in practice it doesn't happen — the same handful of dishes cycles round, the fridge contents get forgotten until they spoil, and the weekly discount catalogues go unread even though they're the single easiest way to cut the grocery bill.

Once a week *is* planned, a second chore starts: turning a set of meals into a shopping list. Ingredients repeat across dishes, so the same onion gets written down three times or forgotten entirely, and quantities have to be added up in the head at the shop. Existing meal-planning apps assume a public signup, a cloud account per person, and a structured pantry inventory that has to be kept accurate to be useful — all of which is far more ceremony than a single household wants, and none of which knows anything about Danish grocery discounts.

## Solution

A small tool that runs on the household's own network, shared by everyone living there, with no signup beyond typing an email so the app knows whose preferences to use.

The household keeps a library of Dishes it already knows how to make — a title is enough; ingredients, substitutes and a recipe are optional extras added whenever there's a reason to. Alongside that sits a FridgeContext: freeform notes and photos of what's currently in the fridge, kept as-is and never parsed into an inventory to maintain.

Each Profile has its own PlanningSettings: how many days to plan, how many suggestions per day, whether to lean toward known dishes or unknown ones, what to prioritise (cheap / quick & easy / delicious / healthy), which shops they use, and freeform Inspiration text describing what they're curious to try.

Pressing "Plan my week" gathers all of that — plus the current week's grocery offers, fetched from the Tjek/eTilbudsavis API for the household's preferred shops, filtered to food and ranked — into a single LLM call that returns a whole week of Suggestions at once. Some are pulled straight from the household's library (known dishes); others are invented, steered by the Inspiration text (unknown dishes). Each carries a description, ingredients with quantities, an estimated cost, a prep time, and the offers it draws on.

The week appears as a board of day columns. Clicking suggestion cards selects them; a review step shows every selected dish's ingredients grouped by dish, all ticked by default, with ingredients wanted by more than one dish colour-tinted so redundant copies can be unticked. Confirming pushes them onto the household's ShoppingList — one merged row per ingredient, quantities summed, with a chip per dish that wants it. At the shop, ticking an item strikes it through, holds for three seconds so a mistake can be un-ticked, then fades away. The list can be copied as plain text or downloaded as CSV.

Every PlanningRun is kept, browsable forever from a "Past plans" archive.

## User Stories

### Identifying yourself

1. As a member of the household, I want to identify myself by typing my email and a display name on first visit, so that the app can hold my planning preferences separately from my partner's without me creating an account or a password.
2. As a returning member of the household, I want the app to remember who I am in this browser, so that I land straight on my own settings without re-identifying every visit.
3. As a member of the household whose email already exists, I want typing that email to land me back on my existing Profile, so that I never end up with a duplicate Profile because I typed my name differently.
4. As a member of the household who has cleared their browser storage, I want retyping my email to resolve back to my existing Profile with all its settings intact, so that losing local state costs me nothing.
5. As someone using a shared household tablet, I want a profile switcher listing everyone in the household, so that I can swap to my own preferences without logging anybody out.
6. As someone using a shared household tablet, I want an "Add a profile" entry in that switcher, so that a new person can join without hunting for a separate signup screen.
7. As a member of the household, I want switching profiles to require no password or re-authentication, so that the tool stays as quick to use as a sheet of paper on the fridge door.

### Keeping the Dish library

8. As a member of the household, I want to add a Dish by typing only its title, so that capturing "we make lasagne" takes five seconds and I'm not blocked on filling in a recipe I already know by heart.
9. As a member of the household, I want optional detail to sit behind a single explicit "Add more detail" toggle, so that the form makes clear that everything past the title is genuinely optional.
10. As a member of the household, I want that toggle to reveal ingredients, substitutes and recipe all at once, so that I'm not clicking through a wizard or opening three separate accordions to write down one dish.
11. As a member of the household, I want to record substitutes for a Dish, so that the planner knows what I swap in when an ingredient isn't available or isn't on offer.
12. As a member of the household, I want to mark a Dish as Favourite, so that the planner knows which meals are the indulgent ones I make when I want to spoil myself.
13. As a member of the household, I want to see the whole library as a grid of cards at a glance, so that I can judge in one screenful what we've captured so far.
14. As a member of the household, I want each card to show an excerpt of whatever detail it has, so that I can tell a fleshed-out Dish from a bare title without opening either.
15. As a member of the household, I want to click anywhere on a card to edit that Dish, so that editing doesn't require finding a small button.
16. As a member of the household, I want a delete control that is visually distinct from the edit target and asks for confirmation, so that I can't lose a Dish by mis-clicking a card.
17. As a member of the household, I want re-opening a Dish that already has detail to show that detail expanded, so that I'm not clicking a toggle to see what I already wrote.
18. As a member of the household, I want an inviting empty state on a fresh install, so that the first thing I see tells me what to do rather than showing me an empty grid.
19. As a member of the household, I want the Dish library shared with everyone else living here, so that a dish my partner adds is one I can plan around too.

### Telling the app what's in the fridge

20. As a member of the household, I want to type freeform notes about what's in the fridge, so that I can write "half a cabbage, chicken thighs, yoghurt going off Thursday" without filling in a structured inventory form.
21. As a member of the household, I want to photograph the fridge instead of typing, so that describing its contents costs me one action rather than five minutes.
22. As a member of the household, I want fridge photos to stay attached until I remove them, so that a photo taken on Sunday still informs Wednesday's replan.
23. As a member of the household, I want the photo itself shown to the planner rather than a text summary of it, so that nothing is lost to a second machine's guess at what was in the picture.
24. As a member of the household, I want to see each photo's age, so that I can judge which ones have gone stale and remove them.
25. As a member of the household, I want to remove a fridge photo, so that last week's contents stop steering this week's plan.
26. As a member of the household, I want the FridgeContext shared household-wide, so that whoever last looked in the fridge is the one who has to describe it.
27. As a member of the household, I want to edit the fridge from the planning screen itself, so that updating it and planning around it are one flow rather than two screens.

### Setting planning preferences

28. As a member of the household, I want to set how many days ahead to plan, so that a plan matches the week I actually shop for.
29. As a member of the household, I want to set how many suggestions I get per day, so that I have a real choice each evening without being buried in options.
30. As a member of the household, I want a control for leaning toward known dishes versus unknown ones, so that I can ask for a comfortable week or an adventurous one depending on my mood.
31. As a member of the household, I want to rank cheap / quick & easy / delicious / healthy by dragging them into order, so that I express what matters most this month without assigning numeric weights I'd be guessing at.
32. As a member of the household, I want to pick my preferred shops from the Danish chains the app already knows, so that I don't have to spell "SuperBrugsen" exactly right for discounts to work.
33. As a member of the household, I want an "Other…" option for a shop that isn't in the list, so that an unusual local shop doesn't lock me out of the feature.
34. As a member of the household, I want shop pills to carry recognisable logos, so that I can pick mine by sight rather than by reading.
35. As a member of the household, I want numeric fields to use plus/minus steppers, so that adjusting them on a tablet doesn't mean fighting a tiny native spinner.
36. As a member of the household, I want an Inspiration text box, so that I can steer invented dishes with "more Vietnamese food, less pasta" in my own words.
37. As a member of the household, I want my settings to be mine alone, so that my partner preferring quick meals doesn't override my preferring cheap ones.

### Planning a week

38. As a member of the household, I want one button that plans the whole week, so that the tool's core value costs me a single action.
39. As a member of the household, I want the whole week returned from a single planning pass, so that the same dish doesn't turn up on three different days.
40. As a member of the household, I want the resulting plan to occupy the screen as a board of day columns, so that the answer is what I look at, not the form that produced it.
41. As a member of the household, I want controls collapsed into top-bar chips summarising their current state, so that I can see what I'm about to plan against without those controls crowding out the plan.
42. As a member of the household, I want each suggestion card to show whether it came from our library or was invented, so that I know at a glance whether I'll be cooking from memory or reading a recipe.
43. As a member of the household, I want a known-dish card to name the Dish it came from, so that I can connect the suggestion to the entry in our library.
44. As a member of the household, I want prep time and estimated cost on each card, so that I can pick Tuesday's dinner against the time and money I actually have.
45. As a member of the household, I want a badge on suggestions that use this week's offers, so that the cheap options are visible without opening every card.
46. As a member of the household, I want a Details view per suggestion, so that I can read the full ingredient list and description before committing to it.
47. As a member of the household, I want Details to show which offer was matched to which ingredient, so that I can see where the estimated saving actually comes from.
48. As a member of the household, I want offers that couldn't be tied to a specific ingredient still listed as "also on offer this week", so that a fuzzy match failing doesn't hide a real bargain.
49. As a member of the household, I want to override days, suggestions-per-day and the known-vs-unknown lean for one run only, so that planning a short week doesn't mean editing and then restoring my saved defaults.
50. As a member of the household, I want that override clearly labelled as just-for-this-run with a reset link, so that I'm never in doubt about whether I've changed my defaults.
51. As a member of the household, I want a plan that came back short to be flagged with what I asked for versus what I got, so that I don't mistake a truncated week for a complete one.
52. As a member of the household, I want a "Try again" action on a short plan, so that recovering costs one click.
53. As a member of the household, I want a run that failed outright to still appear in my history, so that the app never silently swallows a request I made.
54. As a member of the household, I want every past plan browsable forever, so that "what was that salmon thing we had in March" is answerable.
55. As a member of the household, I want the archive to show each run's date, day count, status and the fridge notes it was planned against, so that I can find the run I mean without opening each one.
56. As a member of the household, I want the archive to span everyone in the household, so that I can reuse a plan my partner made.
57. As a member of the household, I want an archived plan to still show its offers long after they've expired, so that an old run reads as a complete record rather than a page of blanks.
58. As a member of the household, I want the planner steered toward ingredients that are on offer at my preferred shops, so that the plan cuts the grocery bill without me reading a single catalogue.
59. As a member of the household, I want the planner to work from the fridge as it is, so that food I already own gets used before it spoils.

### Building the shopping list

60. As a member of the household, I want to pick the suggestions I actually intend to cook by clicking their cards, so that choosing from the week is direct manipulation rather than a form.
61. As a member of the household, I want a clear visual mark on selected cards, so that I can see my choices at a glance across the whole board.
62. As a member of the household, I want opening a card's Details not to select it, so that reading about a dish doesn't commit me to it.
63. As a member of the household, I want a bar showing how many dishes I've selected with a way to clear them, so that I can restart a selection without clicking each card again.
64. As a member of the household, I want to review the combined ingredients before they hit my list, so that I don't add flour I already have a kilo of.
65. As a member of the household, I want that review grouped by dish in board order, so that I can reason about it the way I'll cook it.
66. As a member of the household, I want everything ticked by default in the review, so that the common case — add it all — is one click.
67. As a member of the household, I want unticking to grey and strike a row rather than remove it, so that nothing jumps around while I'm working down the list.
68. As a member of the household, I want ingredients wanted by more than one selected dish colour-tinted and labelled, so that overlaps are obvious and I can drop the redundant copies.
69. As a member of the household, I want select-all and deselect-all shortcuts, so that a big review doesn't mean forty individual clicks.
70. As a member of the household, I want the confirm button to count what's ticked and disable at zero, so that I always know what I'm about to add and can't add nothing.

### Shopping

71. As a member of the household, I want one persistent household list rather than a list per week, so that things we ran out of on Tuesday are still on it on Saturday.
72. As a member of the household, I want one row per ingredient however many dishes want it, so that the list is as short as the shop trip actually is.
73. As a member of the household, I want each row's total to be the sum across every dish, so that I buy the right amount without doing arithmetic in the aisle.
74. As a member of the household, I want each dish's share shown as a bare number in its chip, so that I can see where the total came from without the unit repeated four times.
75. As a member of the household, I want mismatched units joined rather than silently summed, so that "5 dl and 2 cups" never quietly becomes a wrong number.
76. As a member of the household, I want source chips coloured by whether the dish is one of ours or one the app invented, so that provenance reads at a glance without opening anything.
77. As a member of the household, I want to add an item that came from no dish at all, so that coffee and washing-up liquid live on the same list as the meal ingredients.
78. As a member of the household, I want hand-added items visibly marked as such, so that I can tell what the planner suggested from what I added myself.
79. As a member of the household, I want ticking an item to strike it through where it stands, so that I can see what I've already put in the trolley.
80. As a member of the household, I want a struck item to linger a few seconds before vanishing, so that mis-ticking is recoverable simply by un-ticking.
81. As a member of the household, I want the list to clear itself as I shop, so that there's no "clear ticked" chore at the end of the trip.
82. As a member of the household, I want to remove an item without buying it, so that changing my mind doesn't mean pretending I bought something.
83. As a member of the household, I want to copy the list as plain text, so that I can paste it into whatever messaging app the person actually going to the shop uses.
84. As a member of the household, I want a CSV download with ingredient, quantity and notes, so that I can open the list in a spreadsheet and it renders Danish characters correctly.
85. As a member of the household, I want the list shared household-wide, so that whoever gets to the shop first buys the right things.

## Implementation Decisions

### Shape of the system

- **Backend**: Python / FastAPI, built out from the existing `src/food_planer/` scaffold.
- **Frontend**: React. The implementer is new to React, so every screen decision above was taken partly on "which of these is simplest to build" grounds; that constraint holds for implementation too. Behaviour should stay simple to implement without that showing up as a limitation in the finished product.
- **Persistence**: plain JSON files on disk. No database.
- **LLM provider**: OpenAI, hardcoded. Multi-provider swapping is deliberately deferred.
- **Deployment**: a single install on the household's home network. There is no multi-tenancy, no signup, no server-side session.

### Domain model

Canonical vocabulary lives in `CONTEXT.md` — Household, Profile, Dish, Tag, Favourite, Known dish, Unknown dish, Inspiration, FridgeContext, FridgeImage, PlanningSettings, PlanningRun, Suggestion, Offer, DiscountData, ShoppingList, ShoppingList item. Use those terms in code, tests and UI copy.

Sharing follows ADR 0001: **Dish, Tag and FridgeContext are shared household-wide; PlanningSettings are per-Profile.** PlanningRun ownership is per-Profile, but the archive is browsable household-wide.

A Dish carries only the `favourite` Tag. The `stable` tag was dropped — being in the library already makes a dish *known*, so no tag is needed to say so.

### Data storage layout

A gitignored `data/` directory at the repo root, one JSON file per entity type:

- `profiles.json` — Profile records, each with its PlanningSettings nested inline
- `dishes.json` — Dish records, each with its Tags inline
- `fridge_context.json` — a single FridgeContext object
- `shopping_list.json` — a single ShoppingList object
- `planning_runs.json` — every PlanningRun, never pruned
- `data/fridge_images/` — downscaled fridge image binaries (see ADR 0002; `data/` is no longer JSON-only)
- `data/icons/` — shop logo images, `<slug>.<ext>`

There is no `household.json`: the Household is implicit as "this install", not a listed entity.

**Concurrency** assumes a single FastAPI worker process. Each file loads into an in-memory cache at startup paired with its own `asyncio.Lock`. A write acquires that file's lock, mutates the in-memory object, writes to disk atomically (temp file + rename, so a crash can't leave a half-written file), then releases. Reads hit the cache directly. Whatever runs the app in production must guarantee the single-worker constraint — see the open question in Further Notes.

**Ids** are backend-generated UUID4 hex strings for every entity. No counter to maintain across whole-file atomic rewrites, no collision risk when two Profiles write concurrently, and safe to use directly as React keys.

### Discount sourcing

Both originally-named sites (`etilbudsavis.dk`, `365discount.coop.dk`) are front ends for the same platform — **Tjek** (formerly ShopGun). `365discount` is simply one dealer inside Tjek's catalog network. So there is **one dedicated JSON API client against `https://api.etilbudsavis.dk/v2/...`**, not HTML scraping, not a fetcher per site, and not LLM-driven browsing.

Pipeline:

1. Fetch and cache `GET /v2/dealers` (paginated, `limit=200`, page via `offset`; ~301 dealers, cheap to hold in full). Refresh daily.
2. Resolve each preferred shop in PlanningSettings to a `dealer_id` by name match against that cached list. Fuzzy/substring match on `dealer.name` is sufficient.
3. For each resolved dealer, `GET /v2/offers?dealer_ids=<id>` (optionally scoped by `catalog_ids` from `GET /v2/catalogs?dealer_ids=<id>`).
4. Normalise each raw offer into the `Offer` shape below.
5. Any preferred shop that resolves to no dealer falls back to general web search, producing a lower-confidence, largely free-text record tagged `source: "web_search"` — not coerced into looking as structured as it isn't.
6. Cache and rate-limit conservatively: at most once per day or once per PlanningRun, whichever is less frequent. Offers only change weekly.

Prefer the `dealer_ids` / `catalog_ids` listing endpoints over `/v2/offers/search` — the search endpoint is fussy about literal Danish characters and returns an empty array rather than an error on a mis-encoded query.

`Offer` shape (deliberately close to the raw Tjek fields, so the adapter stays thin):

```
Offer
  id                str      # source offer id, or generated for web_search records
  source            enum     # "tjek_api" | "web_search"
  item_name         str      # Tjek `heading`
  description       str?     # Tjek `description` — free text: pack promos, unit-price notes
  shop              str      # dealer/chain name
  price             float
  pre_price         float?   # only populated when the offer advertises a markdown
  discount_percent  float?   # derived from pre_price when present, else null
  currency          str      # "DKK"
  unit_size         str?     # derived from Tjek `quantity`
  valid_from        date     # Tjek `run_from`
  valid_to          date     # Tjek `run_till`
  category          str?     # unreliable — Tjek's category_ids is empty on most offers
  image_url         str?
  fetched_at        datetime
```

Two fields need care downstream: `pre_price` is null on most offers (many are a flat weekly price, not a markdown), so `discount_percent` is only computable for a subset; and `category` must not be relied on for filtering — the API's `category_ids` is empty on the vast majority of offers, so food-relevance is determined from `item_name`/`description` text instead.

**ToS caveat — carry this forward explicitly.** The `api.etilbudsavis.dk` v2 endpoints work unauthenticated today and are used openly by small OSS projects, and that is the pragmatic path here. But Tjek's Terms (linked from every API response header) frame these as licensed-partner APIs, restrict re-use and redistribution, cap volume, and specifically forbid using retrieved data to train, develop or improve AI/ML models. Feeding offers as runtime context into one prompt per PlanningRun is retrieval rather than training, but it is close enough to the letter of that clause that it should be an accepted, called-out, low-volume personal-use risk — not a silent assumption. Mitigation: keep call volume trivially low, cache, redistribute nothing, train nothing.

### LLM contract

**Prompt composition.** One call per PlanningRun, composed of:

- The full Dish library verbatim (title, tags, ingredients where present). Household libraries are small; filtering is premature.
- FridgeContext text as-is, plus every persisted FridgeImage as direct image input.
- PlanningSettings: `daysToPlan` and `suggestionsPerDay` as plain numbers; priority order, known-vs-unknown lean and Inspiration text translated by the backend into natural-language instructions — models follow prose more reliably than a raw settings blob.
- DiscountData, after a selection pipeline: (1) a keyword denylist strips non-food offers, since `category` is too unreliable to filter on; (2) hybrid ranking — offers whose keywords match Dish ingredients first, remaining slots filled by `discount_percent` — capped at roughly 100 offers. Zero relevant offers after filtering means proceed silently with no discount-steering for that run.

**Enforcement.** OpenAI Responses API with `text.format` set to `{type: "json_schema", strict: true}`. Under strict mode every property must appear in `required`, so optionality is expressed as nullable unions rather than omission. The root schema is an object with a nested array property, not a bare array.

**Model choice** is a config value, not a hardcoded name — defaulting to OpenAI's current cheapest Structured-Outputs-capable model, so the spec doesn't go stale as models turn over.

**Response shape** — the whole run comes back in one call so the model can avoid repeating dishes across the week:

```
{ days: [ { day: int, suggestions: Suggestion[] } ] }

Suggestion
  title             str
  description       str
  ingredients       [{ name: str, quantity: str }]   # quantity stays free text ("200 g", "1 pinch")
  estimatedCost     float                            # DKK
  prepTimeMinutes   int
  sourceDish        str | null                       # Dish id; null means unknown dish
  discounts: [{ offerId, matchedIngredient }]          # offerId is a short per-run ref ("o12")
```

*Amendment:* the model no longer writes offer details itself. Each offer in the prompt carries a short per-run `[id]`; the model cites it with the ingredient it covers, and the backend replaces each reference with the full offer (`offerId` = Tjek id, `productName`, `description`, `shop`, `price`, `originalPrice`, `discountPercent`, `unitSize`, `validFrom`, `validUntil`, `imageUrl`, `matchedIngredient`) before persisting — so prices can't be invented, a made-up id is dropped, and the stored run stays denormalized. Non-food filtering also uses the title of the tilbudsavis an offer was printed in (e.g. "Bilka Nonfood Uge 43"). A chain whose fetch fails is named on the run's `offersUnavailable` and the plan proceeds without it (#11's provisional default).

`ingredients[].quantity` is deliberately *not* split into number + unit. `discounts` is a **denormalized array**, not a list of ids — this amends the original `discountIds` decision. Ids only pay off against a durable store; DiscountData is fetched per-run and expires within the week, while the archive keeps runs forever, so an id-based lookup would render an empty Details panel a month later. `matchedIngredient` is the ingredient **name string** (not an index — indices break when lists drift, and the name is what gets displayed) that the backend's fuzzy keyword pass tied the offer to, or `null` for an unmatched offer.

**Failure handling.**

- Safety refusal → no retry, fail immediately, persist `status: "failed"` with no Suggestions.
- Truncation (`max_output_tokens` hit) → exactly one retry with days and suggestions-per-day halved. Success on that retry persists as `status: "partial"`, carrying `requestedDays` / `requestedSuggestionsPerDay` alongside the actuals so the UI can't mistake a short week for a complete one. Failure on that retry persists as `status: "failed"`.

**Persistence.** Every PlanningRun is written as its own record in `planning_runs.json` — id, timestamp, profile, the structured output, and lightweight metadata (Dish ids available at run time, the denormalized discounts). Raw prompt and response *text* is not stored, to avoid duplicating the Dish library and offer text into every run's record forever.

### Fridge images (ADR 0002)

A FridgeImage is **persistent**, not transient. It is stored by the Household, downscaled to roughly 1024px on the long edge on ingest (images bill as tokens on every run they take part in, and full phone resolution buys nothing for "what is in this fridge"), and passed **directly to the model as image input on every PlanningRun**.

This overturns the earlier "summarise once, discard the image" model. Summarising and discarding is lossy at exactly the moment fidelity matters — the plan then works from a second model's guess at the photo, and the summary can't be re-derived once the photo is gone. Passing the image directly also removes an entire LLM call from the flow.

Upload happens eagerly during the fridge-modal save, via the Files API with `purpose: "vision"` and an `expires_after` window anchored at `created_at` (~30 days). The resulting `openaiFileId` is stored on the image record. Cleanup is belt-and-braces: explicit delete when the local image is removed, with expiry as the safety net for anything a crash or a wiped `data/` missed. **The local file is the source of truth** — a `file_id` that has expired or been revoked is silently re-uploaded mid-run rather than degrading the plan.

Consequence for the UI: a fridge photo can go stale without the app knowing, and only a person can judge that. So removal is manual only, and each image's age is shown.

Consequence for #6's flow: there is **no "Analyzing image…" step** — there is no separate analysis pass left to narrate. The fridge modal's waiting moment is the upload itself.

### Backend API surface

REST over `/api`. **No versioning** and FastAPI's stock `{"detail": "..."}` error body with real status codes — frontend and backend ship together as one install, so there is no second consumer to version against or to warrant a custom error envelope. The one failure the UI genuinely branches on (`success` / `partial` / `failed`) travels in the PlanningRun body, not in an HTTP error.

**Profile scoping is explicit in the path or body, never an ambient `X-Profile-Id` header.** Only PlanningSettings and PlanningRun ownership are profile-scoped; Dishes, FridgeContext and the ShoppingList are household-shared, and a header would imply otherwise.

*Profiles & Settings*

| Endpoint | Notes |
| --- | --- |
| `POST /api/profiles/identify` | `{email, name}` → Profile. Find-or-create; an existing email wins and the typed name is discarded |
| `GET /api/profiles` | the switcher list |
| `GET /api/profiles/{id}` | resolves the stored pointer; **embeds** PlanningSettings |
| `PUT /api/profiles/{id}/settings` | the Settings screen saves settings alone |

Embed-on-read / separate-on-write is deliberate: settings are already stored inline in `profiles.json`, so embedding makes app startup a single request, while the Settings screen shouldn't round-trip name and email just to save a slider.

*Dishes* — `GET /api/dishes` (the whole library; it's small and the grid loads it all), `POST /api/dishes`, `PUT /api/dishes/{id}`, `DELETE /api/dishes/{id}`. Full-replace `PUT` rather than `PATCH`, because the edit modal always holds and submits the complete Dish, and `PUT` makes "clear the recipe field" expressible as `recipe: null` instead of `PATCH`'s ambiguity between omitted and cleared. No single-dish `GET` — nothing would call it.

*FridgeContext*

| Endpoint | Notes |
| --- | --- |
| `GET /api/fridge-context` | `{text, images: [{id, mimeType, addedAt}]}` |
| `PUT /api/fridge-context` | text only, plain JSON |
| `POST /api/fridge-context/images` | multipart → the new image record |
| `GET /api/fridge-context/images/{id}` | raw bytes, so the modal can render thumbnails |
| `DELETE /api/fridge-context/images/{id}` | removes locally **and** at OpenAI |

*PlanningRuns*

- `POST /api/planning-runs` with `{profileId, settingsOverride?: {daysToPlan, suggestionsPerDay, knownVsUnknownBias}}` → the finished PlanningRun, **synchronously**. `settingsOverride` is the just-for-this-run adjustment and is never written back to the Profile.
- `GET /api/planning-runs` → the household-wide archive as **summaries** (`id, createdAt, profileId, profileName, dayCount, status, fridgeSnippet`), rather than shipping every suggestion of every week to draw a list.
- `GET /api/planning-runs/{id}` → one full run.

Synchronous rather than `202` + polling: much simpler for a new-to-React frontend, and the usual objection doesn't apply — every run is persisted server-side regardless, so a dropped connection loses the wait, not the plan. Revisit only if this ends up behind a reverse proxy with a 60s timeout.

A `status: "failed"` run returns **200 carrying the PlanningRun body**, not a 5xx. A failed run is a real persisted domain record that appears in Past plans; returning it as an HTTP error would mean the archive can show you something the API refuses to hand over. 5xx stays reserved for the backend actually breaking.

*ShoppingList*

- `GET /api/shopping-list` returns **backend-merged rows**: `{name, totalQuantity, sources: [{dishTitle, kind, share}], lineIds}`.
- `POST /api/shopping-list/items` takes an **array** of `{name, quantity, source: {suggestionTitle, kind} | null}` — the bulk add from the ingredient review, and the same endpoint for a single hand-typed item (`source: null`).
- `POST /api/shopping-list/items/remove` with `{lineIds}` removes a merged row. A `POST .../remove` rather than `DELETE` with a body, because a long list would blow a query-param URL limit and a `DELETE` body is the sort of technically-legal thing that gets silently dropped somewhere in the chain.

**Merging lives in Python, not React.** The summing and unit-joining rules are the fiddliest logic in the app: in Python they are a pure function with unit tests behind an HTTP seam; in React they are a `useMemo` debuggable only in a browser. The API returns pre-merged rows.

*Shops* — `GET /api/shops` → `[{slug, name, hasIcon}]`, `GET /api/shops/{slug}/icon`. The chain list is backend-owned because the discount fetcher already maps preferred shops onto Tjek dealer ids, so the canonical slug↔chain mapping exists server-side either way; duplicating it in the frontend would create two lists that must agree. `hasIcon` lets the frontend choose the colored-initial fallback without a failed image request per pill. Slug rule: lowercase, spaces → hyphens, æ/ø/å stripped.

**There is no `GET /api/discounts`.** Discount fetching, food-filtering and ranking stay entirely inside the planning pipeline; the denormalized `discounts` array on each Suggestion means the frontend never needs a lookup. *Amendment:* `GET /api/shops/{slug}/offers` → `{shop, dealer, offers: Offer[], fetchedAt}` now backs a read-only **Tilbudsavis** screen for browsing one chain's current offers (unfiltered, cached a day per chain). It is a browser, not a lookup — Suggestions still carry their discounts denormalized.

*Prompt* — `GET /api/prompt`, `PUT /api/prompt` (`template: null` resets to the default), `POST /api/prompt/preview`. The planning prompt is one household-wide template, edited from the Settings screen, with backend-derived values injected wherever a `{{variable}}` appears; a template naming an unknown variable is refused with a 422. The default template reproduces the prose composition described under "LLM contract".

### Screen: Dish Library

Card grid, three columns. Each card shows the title; then, only when set, a Favourite (⭐) label below the title — no row is reserved when there is no tag, and the freed space goes to a longer excerpt (roughly 130 chars untagged, 70 tagged). Below that, an excerpt of whichever optional field is filled first, in the order recipe → ingredients → variants.

A trash-can icon sits top-right of the card and deletes with a confirm step; clicking anywhere else on the card opens the edit view. There is no separate Edit button and no bottom action row.

"+ Add Dish" appears in the toolbar and as a dashed placeholder tile at the end of the grid; the empty state is a single centered "+ Add your first dish". All open the same flow.

The add/edit modal is centered. Title is the only required field — large input, autofocused, Save disabled until non-empty. A Favourite toggle chip sits directly below it. Below that, one explicit **"+ Add more detail (optional)"** toggle reveals all three optional fields at once, in the order **Ingredients → Substitutes → Recipe/instructions**, each its own labeled textarea with a caption reiterating that they're optional. Not per-field accordions, not a wizard — one toggle, one reveal. Editing a Dish that already has any optional field filled opens with that section pre-expanded. Cancel discards; Save commits and closes.

This is also the simplest of the prototyped variants to build: one boolean `moreOpen` flag, no accordion-per-field state and no wizard step machine.

### Screen: Settings

A boxed layout:

- One card holding days-to-plan, suggestions-per-day and the known-vs-unknown slider together.
- One card holding priority order as a drag-to-reorder list (cheap / quick & easy / delicious / healthy).
- A full-width card for preferred shops as a **pill picker over the fixed Danish-chain list**, plus an "Other…" pill. Freeform shop text was rejected — it has to be spelled exactly right to resolve to a dealer. Each pill carries a logo image loaded from `data/icons/<slug>.<ext>`, with an automatic colored-initial badge fallback for any chain without a file yet.
- A full-width Inspiration textarea.

Numeric fields use a stepper — a narrow number box with `−`/`+` buttons in one bordered pill — rather than the native browser spinner.

### Screen: Plan a Week

The plan owns the screen: horizontally-scrolling day columns, one per planned day, with compact suggestion cards stacked inside each.

Controls collapse into a top bar: "⚡ Plan my week", a fridge chip showing the current FridgeContext text (opens a modal editor), a settings chip summarising this run's settings (opens a modal), and "🕘 Past plans".

**FridgeContext modal**: text editing plus photo upload. The wait during save is the upload itself — there is no analysis step.

**Per-run settings override** lives behind the settings chip: days, suggestions/day and the known-vs-unknown slider, adjustable for this run only, labelled as such, with a "Reset to my defaults" link. The Profile's saved PlanningSettings are never mutated from this screen.

**Suggestion cards** show title, description, and small tag chips — known-dish (naming the source Dish) vs. "✨ New to you", prep time, estimated cost, and a discount badge counting the `discounts` array ("🏷️ 2 on offer"). Ingredients are not listed on the card; a Details affordance opens the full suggestion, rendering matched offers against their ingredient row and unmatched ones below as "also on offer this week".

**Selection → ingredient review**, replacing any per-card add button:

- Clicking anywhere on a card toggles selection: a filled green check circle on the card's top-right corner plus an accent border ring. The Details button stops the click from reaching the card and does not select.
- A bottom action bar appears while anything is selected: "N dishes selected", a Clear link, and **Add ingredients**.
- That opens a modal reviewing every selected dish's ingredients, **grouped by dish** (day name + ingredient count in each group header), in board order. All ingredients start ticked; unticking greys and strikes the row rather than hiding it. Select-all / deselect-all shortcuts; the confirm button counts what's ticked and disables at zero.
- Any ingredient appearing in **more than one selected dish** gets a colour tint shared across its rows (six tints, assigned per distinct duplicated ingredient) plus an "in N dishes" label, so overlap is visible and redundant copies can be unticked.
- Confirming adds the ticked ingredients to the ShoppingList, clears the selection, and shows a brief toast.

Card selection is **pure frontend state** — never sent to the backend, gone on refresh. Selection is a means to an end; the durable outcome is the ShoppingList items themselves.

**Past plans** lists every run for the Household with timestamp, day count, status and the fridge snippet it was planned against; picking one loads it onto the board. Nothing is pruned — a household produces a handful of runs a week.

**Partial runs** surface as a banner above the board stating what was asked for versus what came back, with a "Try again" action.

### Screen: Shopping List

A flat merged checklist in one narrow column. One row per ingredient no matter how many dishes want it — a shared ingredient is a single merged row, never one row per dish.

Each row: a tickbox, the ingredient name with its total amount beside it, and a row of source chips underneath. A trailing ✕ removes an item without buying it. A single "Add something not from a dish…" field sits above the list, Enter to add; hand-added items get an amber "✎ …" chip instead of source chips.

**Ticking**: ticking strikes the item through **in place**, it dwells there **3 seconds**, then fades out over **1 second** and is gone. No "Ticked" section, no "Clear ticked" button, no undo toast — the list clears itself, and the dwell window *is* the undo (un-tick inside it and the item stays, timers cancelled). Consequence: ticked-ness is purely transient UI state, and `shopping_list.json` needs **no `ticked` flag** — an item is either outstanding or deleted, and the four seconds in between never touch disk.

**Quantities**: an ingredient's headline amount is the **sum across every dish** that wants it. Each dish's share shows as a **bare unitless number** inside its source chip, since the unit is already stated once on the total — `Potatoes · 1200 g` with chips `🍽 Frikadeller 800` and `✨ Miso-glazed salmon 400`. The bare number appears only when more than one dish wants the ingredient; a single-dish item's chip is just the dish name. Where two dishes ask in units that don't match, the amounts are **joined rather than summed** and each dish keeps its own unit — the LLM contract doesn't constrain units, so this case can't be assumed away.

**Provenance**: source chips on the row, one per Suggestion, coloured by kind — green 🍽 for a known dish from the library, blue ✨ for an unknown dish the LLM invented. Deeper detail (which run, which day, which Profile) is deliberately not surfaced here; the chip is the whole story.

**Export**:

- **Copy list** — a modal with a plain-text preview and a Copy button. Unticked items only, totals with each dish's share in brackets.
- **Export CSV** — downloads `shopping-list.csv` with exactly three columns, `Ingredient, Quantity, Notes`. One row per outstanding ingredient; Notes carry the provenance, one note per dish, joined with `;` when there is more than one, and the hand-written note for items with no dish behind them. A shared ingredient's note carries that dish's share, since Quantity holds the total. Standard CSV quoting for fields containing commas or quotes, and a UTF-8 BOM so Excel reads æ/ø/å back correctly.

```csv
Ingredient,Quantity,Notes
Potatoes,1200 g,Frikadeller 800; Miso-glazed salmon with sesame greens 400
Onions,5,Chili con carne 2; Lasagne 2; Frikadeller 1
Minced beef,500 g,Chili con carne
Coffee,500 g,we're just out
```

The **native share sheet is deliberately not part of the design** — `navigator.share` requires HTTPS, which a home-network install served over plain HTTP doesn't have. Copy and CSV both work anywhere.

### Profile identify flow

Email is a backend lookup key. A Profile record is `{id, email, name, settings}`. Submitting an email either matches an existing Profile or creates a new one; there is only one Household per install, so no cross-household disambiguation is needed.

The identify screen is **one single-step form asking for email and display name together**, submitted at once. If the email matches an existing Profile, the typed name is discarded and the existing Profile becomes current; if it doesn't, a new Profile is created with the typed email and name. No async validation while typing, no branching UI — chosen for implementation simplicity.

`localStorage` holds only `foodPlanner.profileId`, a pointer. On load the app fetches the full Profile (name, PlanningSettings) from the backend using that id. The backend is the single source of truth.

The profile switcher is fetched from the backend and lists every Profile in the Household plus a trailing **"Add a profile"** entry that opens the same email+name form. Picking a Profile updates `foodPlanner.profileId`. There is no re-auth step.

Cleared browser storage falls straight out of this model: the identify screen shows again, and retyping the previously-used email resolves back to the same Profile. No data is lost and nothing is re-created.

## Testing Decisions

### What makes a good test here

A good test states something a person would recognise as a promise the app makes — "ticking every dish that wants onions gives me one row saying five onions", "an email that already exists doesn't create a second Profile", "a run that hit the token ceiling comes back marked partial with what I asked for still visible". It exercises the system through the same door the frontend uses, and it says nothing about how the answer was computed. A test that names an internal function, a file on disk, or a cache is testing the current implementation rather than the behaviour, and will have to be rewritten the first time either changes for a good reason.

### The seam

**There is one seam: the HTTP API.** Tests drive a FastAPI `TestClient` against `/api` and assert on response bodies.

Everything settled above is reachable from there — Dish CRUD, identify and find-or-create, settings read/write, fridge text and image upload, planning runs and the archive, shopping-list add/merge/remove, the shop list. Merging, prompt composition, offer filtering and ranking, the truncation-and-halve retry, and the atomic-write persistence layer are all **internal** and are tested through the endpoints that expose them, not directly. That is the reason merging was placed in Python in the first place: behind this seam it is a pure function whose behaviour is assertable, rather than a `useMemo` observable only in a browser.

Three things are configured per test rather than mocked:

- **`data/` points at a temp directory**, so each test starts from a known, empty household and disk state is real (which is what makes the atomic-write behaviour worth anything).
- **The OpenAI client is a fake**, injected via FastAPI `dependency_overrides`. It returns canned structured responses, and can be told to refuse, to truncate once then succeed, or to truncate twice — which is how `success` / `partial` / `failed` get covered without spending money or depending on a model's mood.
- **The Tjek client is a fake**, injected the same way, returning canned dealer and offer payloads shaped like the real ones documented above (including the awkward cases: `pre_price: null`, empty `category_ids`, a preferred shop that resolves to no dealer).

Both fakes exist because both are network calls to third parties whose responses are non-deterministic and, in OpenAI's case, billed. Nothing else gets faked — the JSON persistence layer, the merge logic, the ranking pipeline and the routing all run for real.

### What gets tested

Behaviour worth pinning at this seam, roughly in order of how much it would hurt to get wrong:

- **ShoppingList merging** — several dishes wanting the same ingredient producing one row; totals summed; each dish's share preserved on its source chip; mismatched units joined rather than summed; a hand-added item with no source; removing a merged row by its `lineIds`.
- **PlanningRun statuses** — `success`, `partial` (carrying `requestedDays`/`requestedSuggestionsPerDay` alongside the actuals), and `failed` returning **200 with the run body** rather than a 5xx; a failed run still appearing in the archive.
- **Per-run settings override** never mutating the Profile's saved PlanningSettings — assert by reading the Profile back after a run.
- **Identify find-or-create** — a new email creating a Profile; an existing email returning the existing Profile with the typed name discarded and no duplicate created.
- **Dish CRUD**, including `PUT` with `recipe: null` actually clearing the field.
- **Discount pipeline** — non-food offers denylisted out; ranking putting ingredient-matched offers ahead of merely-high-`discount_percent` ones; the ~100 cap holding; zero relevant offers proceeding silently rather than failing; a preferred shop absent from the dealer list falling through to the lower-confidence path.
- **Denormalized discounts** — a run's Suggestions still carrying full offer detail (and rendering-relevant fields) rather than ids, so an archived run remains complete after its offers expire.
- **Fridge images** — upload returning a record; the bytes endpoint serving them back; delete removing the record; a stale/expired `openaiFileId` triggering a silent re-upload rather than degrading the run.
- **Persistence across restart** — writing through the API, rebuilding the app against the same temp `data/`, and reading the same state back.

### Prior art

There is none — `src/food_planer/` is an empty scaffold and no tests exist yet. The first test file therefore sets the pattern, and should be written as such: a session-scoped `TestClient` fixture, a function-scoped temp-`data/` fixture, and the two fake clients as fixtures wired through `dependency_overrides`. Every later test should be able to start from those four fixtures and add nothing.

The four prototype HTML files on the `prototype/*` branches are the prior art for **behaviour**, not for tests — they are the settled reference for what each screen does, and are worth opening when a spec sentence above is ambiguous.

## Out of Scope

- **Public or multi-tenant hosting with real user signup.** Ruled out in favour of a household-local tool with a lightweight per-browser email identifier.
- **Password-based auth, server-side sessions, or any re-authentication step.** Identification is typing an email, remembered locally. Anyone on the home network who can reach the app can use any Profile.
- **Structured or parsed fridge inventory.** FridgeContext stays freeform text and images fed to the model as-is; there is no item-level pantry with quantities to keep accurate.
- **Multi-provider LLM support.** OpenAI is hardcoded; the only concession is that the model *name* is config rather than a literal.
- **A database.** Plain JSON files, single worker, whole-file atomic rewrites.
- **A `GET /api/discounts` endpoint.** Offers reach the plan only as the denormalized array on a Suggestion. (A read-only per-chain Tilbudsavis browser was later added — see *Shops*.)
- **API versioning and a custom error envelope.** Frontend and backend ship together.
- **Native share-sheet export.** Requires HTTPS, which a plain-HTTP home-network install lacks.
- **A dedicated per-site fetcher for `365discount.coop.dk`**, or LLM-driven browsing of either named discount site. One Tjek API client covers both and generalises to the rest.
- **Splitting ingredient quantities into number + unit**, either in the LLM schema or on the way into the ShoppingList. Quantity is free text; the merge joins what it can't sum.
- **Persisting Plan-a-Week card selection**, or a `ticked` flag on ShoppingList items. Both are transient UI state by design.
- **Aisle grouping, a dedicated in-store "shop mode", or a provenance detail pane** on the Shopping List. All were prototyped and rejected in favour of the flat merged checklist.
- **Frontend unit or component tests.** The single seam is the HTTP API; screens are verified by using them.
- **Merging the prototype branches into `main`.** They stay as reference.

## Further Notes

### Three decisions this spec does not make

The map has three tickets still open. Each is genuinely undecided rather than merely unwritten, so the spec names the question instead of inventing an answer. None blocks a first version — each has an obvious provisional behaviour that a builder will end up implementing by default, noted below so the default is at least a conscious one.

1. **Discount fetch failure handling ([#11](https://github.com/anpom21/food_planer/issues/11)).** It is settled what happens when the fetch returns nothing *relevant* — proceed silently, no discount-steering. It is **not** settled what happens when the fetch itself fails: Tjek times out, errors, changes shape, or the network is down mid-run. Open: does the run abort or proceed without discount-steering? Is there a retry, and how many? Does the user see a banner, a field on the persisted run, or nothing? Should a run planned without discounts be distinguishable in the archive from one planned with them? *Provisional default if built before this closes:* proceed without discount-steering rather than abort, since a plan without offers is still a plan.
2. **Dev/run setup and deployment topology ([#12](https://github.com/anpom21/food_planer/issues/12)).** How the React frontend and FastAPI backend actually run on the home network — a dev server plus API during development, and what ships for everyday use (FastAPI serving the built frontend same-origin, or two processes behind something). This decision determines: whether **CORS middleware** is needed at all (explicitly deferred here from the API-surface work); how the **single-worker constraint** that the whole persistence design depends on is guaranteed; what the start command is and how it survives a reboot; and where `data/` lives relative to the running process, now that it holds image binaries as well as JSON.
3. **LLM cost controls ([#13](https://github.com/anpom21/food_planer/issues/13)).** Nothing currently caps spend. Every run sends the full Dish library, the settings prose, up to ~100 ranked offers, and every persisted FridgeImage as image input — and images bill as tokens *each run*, so four fridge photos are paid for on every replan. Open: a cap on runs per day or per Profile, a `max_output_tokens` ceiling (which interacts with the truncation-and-halve retry), a limit on how many FridgeImages take part in one run, a visible running cost estimate, or a considered "no controls — a handful of runs a week doesn't warrant the machinery."

### Reference material

- **`CONTEXT.md`** and **`docs/adr/0002-fridge-images-persist-and-go-to-the-model-directly.md`** currently live on the `docs/known-unknown-dish-vocab` branch and are not yet merged to `main`.
- **ADR 0001 (`0001-shared-household-data-per-profile-settings.md`) is not in git on any branch.** Its decision — Dish/Tag/FridgeContext shared household-wide, PlanningSettings per-Profile — survives in the map index and is restated above, but the file itself needs restoring.
- The four screen prototypes are the settled behavioural reference, each on its own branch: `prototype/dish-library-screen`, `prototype/settings-screen`, `prototype/plan-a-week-screen` (variant C is the final shape; A and B are kept for comparison), `prototype/shopping-list-screen` (variant A is final). They are single self-contained HTML files with in-memory state, opened directly in a browser with no build step. None are merged to `main` and none should be.

### Two amendments worth knowing about

Reading older map entries or ticket comments will turn up two decisions that were later reversed. Both reversals are already incorporated above:

- **Fridge images were originally transient** — summarised into text by a separate LLM call and discarded. That is overturned by ADR 0002; images now persist and go to the model directly, and the "Analyzing image…" step that the Plan a Week prototype shows is gone with it.
- **Suggestions originally carried `discountIds: string[]`** referencing DiscountData records. That is replaced by the denormalized `discounts` array, so an archived run still renders its offers after they expire.

### On implementation sequencing

Nothing above dictates build order, but two things are worth front-loading. The **HTTP seam and its four fixtures** should exist before the second endpoint does, or the tests will be retrofitted and shaped by the implementation. And **ShoppingList merging** is the one piece of genuinely fiddly logic in the app — summing, unit-joining, per-dish share preservation — which is exactly why it lives in Python; it is the best candidate for the first thing built test-first.
