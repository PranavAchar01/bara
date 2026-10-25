"""Answers a question about one part of a build, for the focus card and the voice agent.

The answer is short and spoken-style (it may be read aloud), grounded only in the build: the
part's card, why it was chosen, what it connects to and its checks. Cerebras first for speed,
Anthropic second, the same keys as the classify call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from bara.llm import CEREBRAS_URL, anthropic_headers

log = logging.getLogger(__name__)

SYSTEM = (
    "You are Bara, a friendly hardware engineer talking someone through a device you just built "
    "for them, out loud, in a quick back-and-forth. Answer the question about one part using only "
    "the build facts given. Lead with the answer itself, in one or two short sentences and under "
    "thirty words, the way a person says it across a desk: no preamble, no restating the "
    "question, no markdown, no lists, no part IDs, numbers said the way people say them. The "
    "question was spoken, so read past any slips or half-words. If the facts don't cover it, say "
    "so in a few words and what you would check. Then offer up to three short follow-up "
    "questions the person might ask next, each under eight words."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "follow_ups"],
    "properties": {
        "answer": {"type": "string"},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
    },
}

MAX_FACTS = 7000


@dataclass
class Answer:
    answer: str
    follow_ups: list[str]
    provider: str
    model: str
    latency_ms: int


def part_facts(build: dict[str, Any], part_id: str) -> dict[str, Any] | None:
    """What the build knows about one part: card, counts, decision, connections, checks."""
    parts = [p for p in build.get("parts") or [] if p.get("part_id") == part_id]
    if not parts:
        return None
    ids = {p.get("instance_id") for p in parts}
    card = parts[0].get("card") or {}
    decisions = [
        {"slot": d.get("slot_id"), "reason": d.get("reason"), "survivors": d.get("survivors")}
        for d in build.get("decisions") or []
        if d.get("chosen_part_id") == part_id
    ]
    names = {
        p.get("instance_id"): (p.get("card") or {}).get("display_name")
        for p in build.get("parts") or []
    }
    connections = []
    for c in build.get("connections") or []:
        ends = [c.get("from") or {}, c.get("to") or {}]
        if any(e.get("instance_id") in ids for e in ends):
            other = next((e for e in ends if e.get("instance_id") not in ids), ends[1])
            connections.append(
                {
                    "to": names.get(other.get("instance_id"), other.get("instance_id")),
                    "kind": c.get("kind") or c.get("net"),
                }
            )
    checks = [
        {"status": c.get("status"), "message": c.get("message")}
        for c in build.get("checks") or []
        if any(s.get("instance_id") in ids for s in c.get("subjects") or [])
    ]
    return {
        "device": (build.get("spec") or {}).get("prompt") or build.get("prompt"),
        "part": {
            "name": card.get("display_name"),
            "function": card.get("primary_function"),
            "summary": card.get("summary"),
            "key_specs": card.get("key_specs"),
            "licence": (card.get("licence") or {}).get("spdx")
            if isinstance(card.get("licence"), dict)
            else card.get("licence"),
            "count": sum(int(p.get("quantity") or 1) for p in parts),
            "labels": [p.get("label") for p in parts if p.get("label")],
        },
        "why_chosen": decisions[:4],
        "connects_to": connections[:24],
        "checks": checks[:12],
    }


def _prompt(facts: dict[str, Any], question: str) -> str:
    text = json.dumps(facts, ensure_ascii=False, default=str)
    if len(text) > MAX_FACTS:
        text = text[:MAX_FACTS] + "…"
    return f"Build facts:\n{text}\n\nQuestion: {question.strip()[:500]}"


def _check(data: Any) -> dict[str, Any]:
    errors = list(Draft202012Validator(SCHEMA).iter_errors(data))
    if errors:
        raise ValueError(errors[0].message[:160])
    data["follow_ups"] = [q for q in data["follow_ups"] if isinstance(q, str) and q.strip()][:3]
    return data


async def _cerebras(prompt: str, model: str, key: str, timeout_s: float) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": True, "schema": SCHEMA},
        },
        "temperature": 0.4,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            CEREBRAS_URL, json=body, headers={"Authorization": f"Bearer {key}"}
        )
    resp.raise_for_status()
    return _check(json.loads(resp.json()["choices"][0]["message"]["content"]))


async def _anthropic(prompt: str, model: str, key: str, timeout_s: float) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        api_key=key, timeout=timeout_s, max_retries=0, default_headers=anthropic_headers()
    )
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
    finally:
        await client.close()
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ValueError("no text in the answer")
    return _check(json.loads(text))


async def answer(
    build: dict[str, Any],
    part_id: str,
    question: str,
    *,
    cerebras_model: str,
    anthropic_model: str,
    timeout_s: float = 20.0,
) -> tuple[Answer | None, str]:
    """(answer, note). None with a reason when the part is unknown or no model answered."""
    facts = part_facts(build, part_id)
    if facts is None:
        return None, "unknown part"
    prompt = _prompt(facts, question)
    attempts = []
    if key := os.environ.get("CEREBRAS_API_KEY"):
        attempts.append(("cerebras", cerebras_model, _cerebras, key))
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        attempts.append(("anthropic", anthropic_model, _anthropic, key))
    if not attempts:
        return None, "no LLM key set"
    notes = []
    for provider, model, call, key in attempts:
        started = time.monotonic()
        try:
            data = await asyncio.wait_for(call(prompt, model, key, timeout_s), timeout=timeout_s)
        except Exception as exc:  # any provider failure moves to the next provider
            log.warning("part ask %s failed: %s", provider, exc)
            notes.append(f"{provider}: {type(exc).__name__}")
            continue
        ms = int((time.monotonic() - started) * 1000)
        return Answer(data["answer"].strip(), data["follow_ups"], provider, model, ms), "ok"
    return None, "; ".join(notes)
