# Bara

Bara turns a one-line gadget prompt into a routed build. Type something like "a wireless split keyboard with an OLED" and Bara either picks an existing open design or assembles one from parts. It lays the parts out in 3D, plans the case and the board, picks firmware, and shows each decision as it happens. After that you can edit the build (swap a part, remove an optional one), and each edit is checked against the same rules before it lands.

Team: Pranav Achar and Nithin. Nithin owns the web UI in `web/`.

## Disclosure

Before the event we wrote the spec and a labelled set of test prompts, and ran a small routing experiment to check the idea was feasible. None of that experiment's code is in this repo. We used Nithin's public UI skill library, the same one we used in Etch. Everything in this repo was written at Cal Hacks 13.0.

## How it works

The browser (Vite, React, React Three Fiber) talks to a FastAPI server over one WebSocket (`/v1/ws`) plus a few REST reads. The contract between them is `spec/SPEC.md` (v1.1.1; the wire `spec_version` is `1.1.0`), with JSON Schemas in `spec/schemas/` and example sessions in `spec/fixtures/`.

A build runs through these stages in order:

1. classify: prompt to a structured spec. If a wrong guess would change the device, the build pauses and asks a clarifying question (2 rounds at most).
2. reuse: the router decides how much of an existing design can be kept.
3. compose: fills the slots that need new parts.
4. place: positions parts in 3D.
5. enclose: the case.
6. board: the circuit board.
7. firmware: driver templates, compiled live when the parts changed.
8. render: scene, camera and the asset preload list.

Once the build is done, an edit stage runs for each accepted edit.

### Router and model providers

Cerebras handles the fast, enum-constrained calls. If it fails or times out, Anthropic takes over. If neither is available, the router uses keyword rules (`server/data/router_keywords.json`) so the build still finishes. Every model call reports which provider served it.

### Tiers

| Tier | Meaning | Case | Board | Firmware |
|---|---|---|---|---|
| exact | one open design meets every hard requirement | the design's own | the design's routed board | prebuilt |
| substitute | one design is close; only failing slots are refilled | the design's own | the design's board | prebuilt unless the swap changes the MCU or pins |
| compose | no design is close enough; parts are chosen slot by slot | generated, neutral gray | autorouted, cached | compiled live |

## Run it

You need [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io) and Node.

```
scripts/dev.sh
```

This starts the server on 127.0.0.1:8790 and the web app on http://localhost:5173, which proxies `/v1` and `/assets` to the server.

To run each half on its own:

```
cd server && uv run bara-server
cd web && pnpm install && pnpm dev
```

Mock mode needs no server and replays the spec fixtures in the browser:

http://localhost:5173/?mock=1&mock_fixture=exact_keyboard

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `CEREBRAS_API_KEY` | primary model provider | unset |
| `ANTHROPIC_API_KEY` | backup model provider | unset |
| `BARA_CEREBRAS_MODEL` | Cerebras model name | `llama-3.3-70b` |
| `BARA_ANTHROPIC_MODEL` | Anthropic model name | `claude-haiku-5-5` |
| `BARA_SPEED` | replay playback rate; higher is faster, `0` skips delays | `1.0` |
| `BARA_MOCK` | server replays fixture streams | on (`1`) |
| `BARA_HOST`, `BARA_PORT` | bind address | `127.0.0.1`, `8790` |
| `BARA_LLM_TIMEOUT_S` | per-call model timeout | `5.0` |
| `BARA_DATA_DIR`, `BARA_SPEC_DIR` | catalog/assets and spec locations | `server/data`, `spec` |

Keys come from the environment only. None are stored in the repo.

## Tests

```
cd server && uv run pytest
cd web && pnpm test
scripts/e2e.sh
```

## Repo layout

```
spec/       contract: SPEC.md, schemas/, fixtures/ (8 streams, REST fixtures)
server/     FastAPI app (src/bara), catalog and assets in data/, tests/
web/        Vite + React + React Three Fiber UI (src/), mock-mode socket
scripts/    dev.sh (run both), e2e.sh (end-to-end check)
e2e/        WebSocket smoke test and live UI check
```

## Known limits (v0)

- Every build replays one of the 8 fixture streams. A prompt that matches a fixture's prompt list plays that fixture; any other prompt is classified and plays the fixture for its tier.
- The composer that builds from the full parts library comes next. Until then, compose-tier results come from the recorded streams, not live part selection.
- STL, 3MF, STEP and KiCad exports are not wired up yet, and part meshes are not shipped, so the viewport draws bounding boxes.
- The part catalog is small and covers keyboards best.
