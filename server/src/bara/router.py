"""Route derivation (SPEC.md 8.12) over catalog data.

No device names live here. Designs, aliases, fixtures and keyword lists are all data loaded at
start-up. The router picks which recorded stream to replay by the stream's content (its
reuse.decided tier, a clarify.request, a terminal E_CRITICAL_PART_MISSING), never by name.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from bara import llm
from bara.catalog import Catalog
from bara.config import Settings

log = logging.getLogger(__name__)

_STRIP_WORDS = {"kit", "build", "style"}
_STOP = {
    "a", "an", "the", "with", "and", "or", "for", "of", "to", "my", "me", "make", "i", "want",
    "need", "some", "something", "please", "that", "this", "it", "on", "in", "is", "but",
    "like", "build", "kit", "style", "new", "one",
}  # fmt: skip
_INPUT_GROUPS = ("sense.", "input.")
_OUTPUT_GROUPS = ("display.", "output.", "comms.")
_CORE_GROUPS = ("input.", "sense.", "output.")
SHORTLIST_FLOOR = 0.5


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\blike a\b", " ", text)
    text = re.sub(r"[^a-z0-9%\s-]", " ", text)
    words = [w for w in text.split() if w not in _STRIP_WORDS]
    return " ".join(words)


# "a mouse that pairs with the keyboard; case colours the same as the keyboard": the device asked
# for is the part before the pairing words. The rest names another device, which must not pick the
# design.
_PAIRING = re.compile(
    r"\s+(?:(?:that|which)\s+)?(?:pairs?|goes|matches)\s+with\b.*$"
    r"|\s+(?:to\s+(?:go|pair)\s+with|to\s+match|paired\s+with)\b.*$",
    re.IGNORECASE,
)


def own_part(prompt: str) -> str:
    """The device a prompt asks for, without what it pairs with or takes its look from."""
    head = prompt.split(";", 1)[0]
    return _PAIRING.sub("", head).strip() or head


def _tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split() if w not in _STOP}


@dataclass
class Route:
    route: str  # exact | substitute | compose | clarify | dead_end | reject
    fixture: str | None  # None: generated out-of-scope stream
    classifier: dict[str, Any] | None  # None: keep the fixture's classifier
    patch_prompt: bool = False
    warnings: list[dict[str, Any]] = field(default_factory=list)
    spec: dict[str, Any] | None = None  # generated spec for the reject route
    reason: str = ""
    design_id: str | None = None


def _fixture_events(fx: dict[str, Any]) -> list[dict[str, Any]]:
    return [s["msg"] for s in fx.get("steps", []) if s.get("dir") == "server"]


class Router:
    def __init__(self, catalog: Catalog, settings: Settings) -> None:
        self.catalog = catalog
        self.settings = settings
        path = settings.data_dir / "router_keywords.json"
        self.keywords: dict[str, Any] = json.loads(Path(path).read_text()) if path.exists() else {}
        self.build_fixtures: list[str] = []
        self.by_route: dict[str, str] = {}
        self._index_fixtures()

    # ---- fixture index by content ------------------------------------
    def _index_fixtures(self) -> None:
        for name, fx in self.catalog.fixtures.items():
            if fx.get("requires_fixture"):
                continue
            steps = fx.get("steps", [])
            if not any(s["dir"] == "client" and s["msg"]["type"] == "build.start" for s in steps):
                continue
            self.build_fixtures.append(name)
            events = _fixture_events(fx)
            types = [e["type"] for e in events]
            last = events[-1] if events else {}
            tiers = [e["payload"].get("tier") for e in events if e["type"] == "reuse.decided"]
            if "clarify.request" in types:
                self.by_route.setdefault("clarify", name)
            elif (
                last.get("type") == "build.failed"
                and last["payload"]["error"]["code"] == "E_CRITICAL_PART_MISSING"
            ):
                self.by_route.setdefault("dead_end", name)
            elif tiers and tiers[0] == "exact":
                self.by_route.setdefault("exact", name)
            elif tiers and tiers[0] in ("compose", "substitute"):
                self.by_route.setdefault(tiers[0], name)
        self.by_route.setdefault("substitute", self.by_route.get("compose", ""))
        log.info("router fixtures: %s", self.by_route)

    def fixture_for(self, route: str) -> str:
        return self.by_route.get(route) or self.by_route.get("compose") or self.build_fixtures[0]

    def is_build_fixture(self, name: str | None) -> bool:
        return bool(name) and name in self.build_fixtures

    # ---- stage 0 -------------------------------------------------------
    def match_prompt(self, norm: str) -> str | None:
        for name in self.build_fixtures:
            for p in self.catalog.fixtures[name].get("match_prompts", []):
                if normalize(p) == norm:
                    return name
        return None

    def name_match(self, norm: str) -> tuple[str, str] | None:
        """Exact phrase match on a design name or alias, then token-set fuzzy >= 0.9."""
        words = norm.split()
        best: tuple[float, str, str] | None = None
        for design_id, design in self.catalog.designs.items():
            names = [design.get("name", "")] + list(design.get("aliases", []))
            for raw in names:
                cand = normalize(re.sub(r"\(([^)]*)\)", r" \1 ", raw))
                for variant in {cand, normalize(re.sub(r"\([^)]*\)", " ", raw))}:
                    if not variant:
                        continue
                    if re.search(rf"(^|\s){re.escape(variant)}($|\s)", norm):
                        return design_id, variant
                    n = len(variant.split())
                    for i in range(0, max(1, len(words) - n + 1)):
                        window = " ".join(sorted(words[i : i + n]))
                        score = SequenceMatcher(None, window, " ".join(sorted(variant.split())))
                        ratio = score.ratio()
                        if ratio >= 0.9 and (best is None or ratio > best[0]):
                            best = (ratio, design_id, variant)
        return (best[1], best[2]) if best else None

    def shortlist(self, norm: str, name_hit: str | None) -> list[str]:
        prompt_tokens = _tokens(norm)
        scored: list[tuple[float, float, str]] = []
        if prompt_tokens:
            for design_id, design in self.catalog.designs.items():
                text = " ".join(
                    [design.get("name", ""), design.get("summary") or ""]
                    + list(design.get("aliases", []))
                    + [p.replace("_", " ") for p in design.get("taxonomy_path", [])]
                )
                overlap = len(prompt_tokens & _tokens(text)) / len(prompt_tokens)
                if overlap >= SHORTLIST_FLOOR:
                    scored.append((overlap, float(design.get("popularity", 0)), design_id))
        scored.sort(reverse=True)
        out = [name_hit] if name_hit else []
        for _, _, design_id in scored:
            if design_id not in out:
                out.append(design_id)
            if len(out) >= 3 + (1 if name_hit else 0):
                break
        return out

    # ---- keyword fallback ----------------------------------------------
    def keyword_classify(self, norm: str) -> dict[str, Any]:
        padded = f" {norm} "
        oos = any(f" {w} " in padded for w in self.keywords.get("out_of_scope", []))
        functions: list[str] = []
        known = set(self.catalog.function_ids())
        for word, fids in self.keywords.get("function_words", {}).items():
            if f" {word} " in padded:
                functions += [f for f in fids if f in known and f not in functions]
        reqs = []
        for word, (facet, value) in self.keywords.get("facet_words", {}).items():
            if f" {word} " in padded and all(r["facet"] != facet for r in reqs):
                reqs.append({"facet": facet, "value": value})
        device_class = "unknown"
        by_group = self.keywords.get("device_class_by_function_group", {})
        for fid in functions:
            group = fid.split(".")[0]
            if group in by_group:
                device_class = by_group[group]
                break
        blocking = None if functions else "primary_function"
        return {
            "scope": "out_of_scope" if oos else "in_scope",
            "device_class": device_class,
            "functions": functions or ([] if not oos else ["other"]),
            "main_purpose": norm,
            "blocking_facet": None if oos else blocking,
            "hard_requirements": reqs,
        }

    # ---- reuse check in code -------------------------------------------
    @staticmethod
    def _value_eq(attr: Any, value: Any) -> bool:
        if isinstance(attr, bool):
            truthy = str(value).lower() in ("true", "yes", "1")
            return truthy == attr
        return str(attr).lower() == str(value).lower()

    def changes_needed(self, design: dict[str, Any], reqs: list[dict[str, Any]]) -> list[str]:
        attrs = design.get("attributes", {})
        return [
            r["facet"]
            for r in reqs
            if r["facet"] in attrs and not self._value_eq(attrs[r["facet"]], r["value"])
        ]

    def reuse_accepts(self, design: dict[str, Any], c: dict[str, Any]) -> bool:
        dc = c.get("device_class")
        if dc not in (None, "unknown", "other") and design.get("device_class") != dc:
            return False
        core = {f for f in c.get("functions", []) if f.startswith(_CORE_GROUPS)}
        return bool(core) and core <= set(design.get("functions", []))

    def dead_end(self, reqs: list[dict[str, Any]]) -> bool:
        attr_facets = set()
        for d in self.catalog.designs.values():
            attr_facets |= set(d.get("attributes", {}))
        on_attrs = [r for r in reqs if r["facet"] in attr_facets]
        if len(on_attrs) < 2:
            return False
        designs = list(self.catalog.designs.values())

        def meets(d: dict[str, Any], r: dict[str, Any]) -> bool:
            attrs = d.get("attributes", {})
            return r["facet"] in attrs and self._value_eq(attrs[r["facet"]], r["value"])

        each = all(any(meets(d, r) for d in designs) for r in on_attrs)
        joint = any(all(meets(d, r) for r in on_attrs) for d in designs)
        return each and not joint

    # ---- main entry ----------------------------------------------------
    async def route(self, prompt: str, options: dict[str, Any] | None) -> Route:
        started = time.monotonic()
        options = options or {}
        forced = options.get("mock_fixture")
        if self.is_build_fixture(forced):
            return Route("mock_fixture", forced, None, reason="BuildOptions.mock_fixture")
        norm = normalize(prompt)
        force_tier = options.get("force_tier")
        if force_tier in ("exact", "substitute", "compose"):
            return Route(force_tier, self.fixture_for(force_tier), None, patch_prompt=True)
        hit = self.match_prompt(norm)
        if hit:
            same = any(
                e["type"] == "spec.ready" and e["payload"]["spec"]["prompt"] == prompt
                for e in _fixture_events(self.catalog.fixtures[hit])
            )
            return Route("match_prompt", hit, None, patch_prompt=not same, reason="match_prompts")

        own = normalize(own_part(prompt))
        name = self.name_match(own)
        name_hit = name[0] if name else None
        shortlist = self.shortlist(own, name_hit)
        schema = llm.classify_schema(
            self.catalog.function_ids(), self.catalog.device_classes(), self.catalog.facet_keys()
        )
        result, notes = await llm.classify(
            prompt,
            schema,
            cerebras_model=self.settings.cerebras_model,
            anthropic_model=self.settings.anthropic_model,
            timeout_s=self.settings.llm_timeout_s,
        )
        warnings: list[dict[str, Any]] = []
        if result is not None:
            c = result.data
            classifier = {
                "stage": "llm",
                "confidence": 0.8,
                "margin": None,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "provider": result.provider,
                "fallback": result.fallback,
            }
            if result.fallback:
                warnings.append(
                    {
                        "warning_id": "w_llm",
                        "code": "llm_fallback",
                        "severity": "info",
                        "message": "The primary model failed; the backup model classified this.",
                        "subjects": [],
                        "stage": "classify",
                    }
                )
        else:
            c = self.keyword_classify(own)
            classifier = {
                "stage": "rules",
                "confidence": 0.5,
                "margin": None,
                "model": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "provider": None,
                "fallback": True,
            }
            warnings.append(
                {
                    "warning_id": "w_llm",
                    "code": "llm_degraded",
                    "severity": "warning",
                    "message": (
                        "No model answered (" + "; ".join(notes) + "). Used keyword rules."
                    )[:300],
                    "subjects": [],
                    "stage": "classify",
                }
            )
        return self.derive(prompt, norm, c, classifier, warnings, name_hit, shortlist)

    def derive(
        self,
        prompt: str,
        norm: str,
        c: dict[str, Any],
        classifier: dict[str, Any],
        warnings: list[dict[str, Any]],
        name_hit: str | None,
        shortlist: list[str],
    ) -> Route:
        functions = list(c.get("functions", []))
        reqs = list(c.get("hard_requirements", []))
        scope = c.get("scope", "unknown")

        def mk(route: str, reason: str, design_id: str | None = None) -> Route:
            return Route(
                route,
                self.fixture_for(route),
                classifier,
                patch_prompt=True,
                warnings=warnings,
                reason=reason,
                design_id=design_id,
            )

        # Rule 1: a named job the engine must not do.
        if scope == "out_of_scope" and functions:
            spec = self.reject_spec(prompt, norm, c, classifier)
            return Route("reject", None, classifier, True, warnings, spec, "out of scope")

        accepted = [
            d for d in shortlist if self.reuse_accepts(self.catalog.designs[d], c)
        ]  # in shortlist order
        accepted.sort(key=lambda d: len(self.changes_needed(self.catalog.designs[d], reqs)))
        name_accepted = name_hit is not None and name_hit in accepted

        # Rule 2: blocking facet, unless cleared in code.
        if c.get("blocking_facet"):
            has_in = any(f.startswith(_INPUT_GROUPS) for f in functions)
            has_out = any(f.startswith(_OUTPUT_GROUPS) for f in functions)
            if not (name_accepted or (has_in and has_out)):
                return mk("clarify", f"blocking facet {c['blocking_facet']}")
        # Rule 3: out of scope with no functions is a vague request.
        if scope == "out_of_scope":
            return mk("clarify", "vague request")
        if self.dead_end(reqs):
            return mk("dead_end", "no design meets every hard requirement")
        # Rule 4.
        if accepted:
            chosen = name_hit if name_accepted else accepted[0]
            changes = self.changes_needed(self.catalog.designs[chosen], reqs)
            return mk("substitute" if changes else "exact", "reuse accepted", chosen)
        # Rule 5.
        if name_hit:
            design = self.catalog.designs[name_hit]
            same_class = design.get("device_class") == c.get("device_class")
            return mk("substitute" if same_class else "compose", "name match", name_hit)
        return mk("compose", "no design fits")

    def reject_spec(
        self, prompt: str, norm: str, c: dict[str, Any], classifier: dict[str, Any]
    ) -> dict[str, Any]:
        device_class = c.get("device_class") or "unknown"
        if device_class not in self.catalog.device_classes():
            device_class = "unknown"
        return {
            "spec_id": "sp_" + re.sub(r"[^a-z0-9]", "", norm)[:16] or "sp_reject",
            "prompt": prompt,
            "normalized_prompt": norm,
            "device_class": device_class,
            "taxonomy_path": [device_class],
            "functions": [
                {"function_id": f, "required": True, "count": 1, "source": "explicit"}
                for f in c.get("functions", [])
            ],
            "hard_requirements": [],
            "soft_requirements": [],
            "leftover_text": None,
            "classifier": classifier,
            "scope": "out_of_scope",
            "scope_reason": (
                "This needs a capability the engine does not build: medical, weapons, jamming, "
                "mains power, rideable vehicles, or something physically impossible."
            ),
            "assumptions": [],
            "ambiguity": {"needs_clarify": False, "missing_facets": [], "blocking_facet": None},
        }
