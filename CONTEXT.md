# Food Planner

A household tool that turns fridge contents, standing preferences, and a personal dish library into AI-generated weekly meal suggestions, prioritized by current discounts.

## Language

**Household**:
The single local install of the app, shared by everyone living there. Owns the shared Dish library and shared FridgeContext; has one or more Profiles.

**Profile**:
One person living in the Household (e.g. "Andreas", a partner). Owns its own PlanningSettings. Does not have a separate Dish library or FridgeContext — those are shared at the Household level.
_Avoid_: User, account (implies auth/multi-tenant signup, which this is not)

**Dish**:
An entry in the Household's shared library of meals the person likes to make — by definition a *known dish*. Has a title, and optional (+) details: ingredients, recipe/instructions, and recipe variants (substitutes). Can carry Tags.
_Avoid_: Recipe (a Dish's optional recipe text is one field on it, not the whole concept), meal

**Tag**:
A label on a Dish. One tag currently defined: `favourite`. A Dish can carry it or not.
_Avoid_: Treat, category

**Favourite** (tag):
Marks a Dish as indulgent / extra-nice — something made when the person wants to spoil themselves a bit (e.g. pizza, spareribs, steak, pancakes).
_Avoid_: Treat

**Known dish**:
A Dish already in the Household's library — the LLM can pick it directly (a Suggestion's `sourceDish`). Contrasts with an *unknown dish*.
_Avoid_: Stable dish, staple (a `stable` tag used to mark these; dropped — being in the library already makes a dish "known", no separate tag needed)

**Unknown dish**:
A meal the LLM invents that isn't in the Household's library (a Suggestion with no `sourceDish`), steered by the Inspiration text.
_Avoid_: New dish, novel dish (older phrasing — "unknown" is now the canonical term, paired with Known dish)

**Inspiration**:
Freeform text on a PlanningSettings describing the kinds of unknown dishes the person is curious to try. Used to steer the LLM when a planning run favors unknown dishes over known ones.

**Fridge** ("What is in the fridge?"):
The Household's itemised stock, shared household-wide, in two kinds. Fed to the LLM on every PlanningRun as two named lists.
_Avoid_: FridgeContext, FridgeImage (the earlier freeform-text-and-persistent-photos model, now replaced; photos are scanned once and never kept)

**Fresh item**:
Something in the house that keeps for less than about a month (milk, chicken, salad). Added by hand — picked from the common items, typed, or found by a photo scan — and removed by hand once used up. The planner is told to use these up first.

**Pantry staple**:
Something that keeps for a month or longer (rice, flour, spices). Assumed always in the house for now; the planner may use them freely.
_Avoid_: Long-life item

**Common items**:
The pick-list per kind: a built-in basic set plus every name the Household has added before, minus what's already in the Fridge.

**Fridge scan**:
Photos sent once to the LLM, which returns named, classified items for the Household to review before any are added. The photos are not kept.

**PlanningSettings**:
Per-Profile configuration for a planning run: number of days to plan, suggestions per day (default 3/day), known-vs-unknown dish preference, priority order (cheap / quick & easy / delicious / healthy), preferred shops, and Inspiration text.

**PlanningRun**:
One invocation of the LLM for a given Profile, producing a set of Suggestions for the configured number of days.

**Suggestion**:
One LLM-generated meal recommendation produced by a PlanningRun: title, brief description, ingredients, and possibly more. May optionally reference the Dish it was pulled from (`sourceDish`) — a known dish; if absent, it's an unknown dish the LLM invented.
_Avoid_: Recipe suggestion, recommendation

**Offer**:
One discounted product at one shop for a limited period, fetched from an external discount source. Steers a PlanningRun toward cheaper meals, and may be tied to a particular ingredient of a Suggestion.
_Avoid_: Deal, discount, promotion, campaign

**DiscountData**:
The set of Offers gathered for a single PlanningRun, filtered down to food and ranked before it reaches the LLM. Describes one week's prices only — never accumulated into a library.
_Avoid_: Discounts, offer list

**Imported recipe**:
A recipe scraped from a recipe website (valdemarsro.dk so far) into local JSON: title, link, thumbnail, ingredient lines, instructions, times, servings. Not part of the Household's Dish library. A PlanningRun only sees the dinner ones that use a fresh item or an Offer, ranked and capped; a Suggestion based on one links back to it (its `recipe`).
_Avoid_: Dish (that's the Household's own library), Recipe on its own (ambiguous with a Dish's recipe text)

**On hand**:
An ingredient the Household already has — a fresh item (🥬) or a pantry staple (🫙). Marked on Suggestion and Imported recipe ingredients, and never matched to an Offer: there's nothing to buy.

**Match review**:
The model's check of an Offer tied to an ingredient by name when the match isn't 1:1 (a compound like "frilandsæg" for "æg", a multipack, a long heading). Exact matches are tied straight away; review matches only once the model confirms them (`matchedBy: "review"`). In the planning prompt, an Imported recipe's uncertain offers are marked "check offer" for the planner to judge.

**ShoppingList**:
One persistent, household-wide list of ingredients to buy. Accumulates items from any Profile's Suggestions over time (not scoped to a single PlanningRun or week) and is only cleared as items are ticked off / bought.
_Avoid_: Ingredients list (both names were used loosely in early discussion; ShoppingList is the canonical term)

**ShoppingList item**:
One ingredient wanted by one Suggestion — the unit the ShoppingList stores. Several items for the same ingredient are read as a single merged line naming each Suggestion behind it, so the stored shape and the read shape differ on purpose.
_Avoid_: Line, row, entry (each has been used loosely for both the stored item and the merged view of several)
