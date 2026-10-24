"""Stage 1 classify call: Cerebras first, Anthropic second, enum-constrained JSON.

Keys come from the environment only (CEREBRAS_API_KEY, ANTHROPIC_API_KEY). Every call has
a hard deadline (BARA_LLM_TIMEOUT_S, default 60 s, room for a high-effort answer). The
result is validated locally against the same schema the model was constrained with; any
failure moves to the next provider.
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

log = logging.getLogger(__name__)

CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"

CLARIFY_FACETS = ["primary_function", "which_device", "sensed_quantity", "controlled_output"]


@dataclass
class LlmResult:
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: int
    fallback: bool


def classify_schema(
    function_ids: list[str], device_classes: list[str], facet_keys: list[str]
) -> dict[str, Any]:
    """JSON Schema for the classify answer. Every enum comes from the loaded vocab."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "scope",
            "device_class",
            "functions",
            "main_purpose",
            "blocking_facet",
            "hard_requirements",
        ],
        "properties": {
            "scope": {"type": "string", "enum": ["in_scope", "out_of_scope", "unknown"]},
            "device_class": {"type": "string", "enum": device_classes},
            "functions": {"type": "array", "items": {"type": "string", "enum": function_ids}},
            "main_purpose": {"type": "string"},
            "blocking_facet": {
                "anyOf": [{"type": "string", "enum": CLARIFY_FACETS}, {"type": "null"}]
            },
            "hard_requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["facet", "value"],
                    "properties": {
                        "facet": {"type": "string", "enum": facet_keys},
                        "value": {"type": "string"},
                    },
                },
            },
        },
    }


SYSTEM_PROMPT = (
    "You classify one hardware build request for a hobby electronics builder. "
    "Answer only with JSON matching the schema.\n"
    "scope: out_of_scope only when the request cannot be built from hobby electronics and "
    "printed or off the shelf mechanical parts, is physically impossible, or needs a "
    "regulated or unsafe capability (medical diagnosis, weapons, jamming, mains appliances, "
    "rideable vehicles). A vague request is never out_of_scope.\n"
    "functions: every function id the device needs, from the enum.\n"
    "main_purpose: the core job in a few words, without the user's tweaks.\n"
    "blocking_facet: set only when two competent builders reading the request would build "
    "devices that do different jobs. primary_function: only a mood, place or vague wish. "
    "which_device: unrelated alternatives. sensed_quantity: a monitor that does not say "
    "what it measures. controlled_output: a controller that does not say what it controls. "
    "Missing details such as power, colour, size or connectivity never block. "
    "A named product never blocks.\n"
    "hard_requirements: facet values the user stated explicitly, using the facet enum and "
    "the facet's value ids (for example switch_family choc_v1, layout_size percent_60, "
    "wireless ble, split true)."
)


def _validate(schema: dict[str, Any], data: Any) -> dict[str, Any]:
    errors = list(Draft202012Validator(schema).iter_errors(data))
    if errors:
        raise ValueError(f"classify output failed its schema: {errors[0].message[:200]}")
    return data


async def _cerebras(
    prompt: str, schema: dict[str, Any], model: str, key: str, timeout_s: float
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "classify", "strict": True, "schema": schema},
        },
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            CEREBRAS_URL, json=body, headers={"Authorization": f"Bearer {key}"}
        )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _validate(schema, json.loads(content))


async def _anthropic(
    prompt: str, schema: dict[str, Any], model: str, key: str, timeout_s: float
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=key, timeout=timeout_s, max_retries=0)
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": schema},
            },
        )
    finally:
        await client.close()
    if response.stop_reason == "refusal":
        raise ValueError("model refused the classify request")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ValueError("no text block in the classify response")
    return _validate(schema, json.loads(text))


def providers_configured() -> dict[str, bool]:
    return {
        "cerebras": bool(os.environ.get("CEREBRAS_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


async def classify(
    prompt: str,
    schema: dict[str, Any],
    *,
    cerebras_model: str,
    anthropic_model: str,
    timeout_s: float,
) -> tuple[LlmResult | None, list[str]]:
    """Returns (result or None, list of provider failure notes)."""
    notes: list[str] = []
    attempts = []
    cerebras_key = os.environ.get("CEREBRAS_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if cerebras_key:
        attempts.append(("cerebras", cerebras_model, _cerebras, cerebras_key))
    if anthropic_key:
        attempts.append(("anthropic", anthropic_model, _anthropic, anthropic_key))
    for index, (provider, model, call, key) in enumerate(attempts):
        started = time.monotonic()
        try:
            data = await asyncio.wait_for(
                call(prompt, schema, model, key, timeout_s), timeout=timeout_s
            )
        except TimeoutError:
            notes.append(f"{provider} timed out after {timeout_s:.1f} s")
            log.warning("llm %s timed out", provider)
            continue
        except Exception as exc:  # any provider failure moves to the next provider
            notes.append(f"{provider} failed: {type(exc).__name__}")
            log.warning("llm %s failed: %s", provider, exc)
            continue
        latency = int((time.monotonic() - started) * 1000)
        return LlmResult(data, provider, model, latency, fallback=index > 0), notes
    if not attempts:
        notes.append("no LLM key set")
    return None, notes
