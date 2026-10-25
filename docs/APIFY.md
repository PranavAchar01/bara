# Apify in Bara

Apify is the front door of retrieval: every build starts with a run of the `bara-hardware-scout`
Actor (`actors/bara-hardware-scout/`). See its README for what it crawls and returns.

## What works with no account

The engine runs the Actor's code in-process (`server/src/bara/live/apify_scout.py`), so builds,
the build-log step "Scouting open-source designs (Apify scout)", reference-design matching, priced
shopping lists marked "sourced via Apify scout" and the stats all work now. Switch off with
`BARA_APIFY=off`. Set `GITHUB_TOKEN` (optional) to avoid GitHub's 60 requests an hour.

Live demo: `cd server && PYTHONPATH=src uv run python scripts/demo_apify_scout.py "handheld game console"`
Numbers to cite: `GET /v1/apify/stats` (builds, designs found, parts priced, pages crawled).

## What needs the token

Running the Actor on the Apify platform (engine uses the Apify API client) and publishing it.

## Steps for Pranav

1. Sign up (free plan is enough): https://console.apify.com/sign-up
2. Token: Console > Settings > API & Integrations > Personal API tokens > Create. Store it:
   `security add-generic-password -a "$USER" -s APIFY_TOKEN -w` (it prompts; paste there).
3. Start the engine with it in the environment, never in a file:
   `export APIFY_TOKEN=$(security find-generic-password -s APIFY_TOKEN -w)`
4. Push the Actor:
   ```
   npm i -g apify-cli
   apify login            # paste the token when asked
   cd actors/bara-hardware-scout && apify push
   ```
   Run it once in the Console with input `{"query": "handheld game console"}` and check the dataset.
5. Tell the engine which Actor: `export APIFY_ACTOR_ID=<your-username>/bara-hardware-scout`
   (the engine falls back to the local run if the cloud call fails, and says so in the log).
6. Optional: in the Actor's Console settings > Environment variables, add `GITHUB_TOKEN` (secret).

## Publishing for the "Best Actor" prize

Console > Actors > bara-hardware-scout > Publication: set display name "Open Hardware Scout",
the description (from `.actor/actor.json`), category "Developer tools" or "Other", an icon, SEO
title and description; the README is picked up from the repo. Choose a pricing model (free is
fine) and press Publish to Store. The Actor must be public and have at least one successful
run for the listing to look credible. Then submit the Store URL for the prize.
