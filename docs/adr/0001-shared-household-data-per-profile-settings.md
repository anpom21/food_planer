# Shared household data, per-Profile settings

The Household owns one shared Dish library (each Dish with its Tags) and one shared FridgeContext. What is *not* shared is PlanningSettings: those belong to a single Profile. A PlanningRun is owned by the Profile that started it, but the archive of past runs is browsable household-wide.

## Why

The app is one local install shared by everyone living in the household, with no signup beyond typing an email. The things that describe the household — the meals it knows how to make, and what's currently in the fridge — are facts about the household, not about any one person: a dish a partner adds is one anyone can plan around, and whoever last looked in the fridge is the one who should have to describe it. Duplicating that library and that fridge state per Profile would mean the same dish typed twice and the fridge described twice, for no gain.

Planning *preferences*, by contrast, are personal: how many days to plan, how adventurous to be, what to prioritise, which shops to use, what to be inspired by. Those differ between the people in the household and are exactly what the email-per-person identity exists to keep apart. So PlanningSettings hang off the Profile, and a PlanningRun — a personal act of planning against personal settings — is owned by the Profile that ran it.

The archive is the exception that proves the rule: a run is *owned* per-Profile, but it stays worth reading to the rest of the household (reuse a plan a partner already made), so the list of past runs spans everyone.

## Considered options

- **Everything per-Profile.** A Dish library, FridgeContext and settings each scoped to one person. Rejected: it forces every dish and every fridge note to be re-entered per person and makes "a dish my partner added" impossible without a sharing mechanism bolted on top — ceremony this single-household tool exists to avoid.
- **Everything household-wide, including settings.** One shared set of planning preferences. Rejected: it erases the only thing the per-person identity is for. Two people with different tastes and schedules would overwrite each other's preferences on every edit.
- **Shared library and fridge, per-Profile settings** (chosen). Matches how the data actually divides: household facts are shared, personal preferences are not.

## Consequences

- Dish, Tag and FridgeContext are stored once for the Household, not per Profile. `dishes.json` and `fridge_context.json` are single household-wide stores; there is no per-Profile copy.
- PlanningSettings are stored nested inside each Profile record in `profiles.json`. There is no separate settings store and no household-level default.
- A PlanningRun records the Profile that owns it, but `GET /api/planning-runs` returns the household-wide archive (every Profile's runs) as summaries. Ownership scopes *who made it*, not *who can see it*.
- Profile scoping is therefore explicit in the API path or body, never an ambient `X-Profile-Id` header: only PlanningSettings and PlanningRun ownership are profile-scoped, so a blanket header would wrongly imply Dishes, FridgeContext and the ShoppingList are too.
- The ShoppingList follows the same household-shared side of the line as Dishes and FridgeContext — one list for the whole household — even though it is not itself a subject of this decision.
