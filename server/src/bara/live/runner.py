"""Live 8-stage build (BARA_MOCK=0): brief, compose, KiCad board, case, firmware, scene.

Stage order is SPEC 2.1. The KiCad board is built inside `place` (parts are placed by the
board planner and routed there), because the case in `enclose` needs the board outline;
its routing and DRC results are reported in `board`.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
import time
from typing import TYPE_CHECKING, Any

from shapely.geometry import Polygon

from bara.board.evaluate import evaluate as evaluate_board
from bara.board.generic import board_footprint_mm
from bara.live import adapters as A
from bara.live import archetype, completeness, hero, open_designs, retrieval, websearch
from bara.live import blocks as blocks_mod
from bara.live import concept as concept_mod
from bara.live import finish as finish_mod
from bara.live import form as form_mod
from bara.live import identity as identity_mod
from bara.live import reference_design as reference_mod
from bara.live.brief import BriefResult, normalise_brief, spec_from_brief, write_brief
from bara.live.catalog_source import PartSource, merge_into_catalog, model_asset
from bara.live.compose import ASSETS_DIR, Composer, ComposeResult, Slot
from bara.live.fetch import as_overlay
from bara.live.firmware import make_firmware
from bara.live.layout import KeyboardPlan, plan_keyboard
from bara.util import error_obj

if TYPE_CHECKING:
    from bara.engine import BuildRun, Engine

log = logging.getLogger(__name__)
# p90 of measured live builds (2026-10-24 suite); the fixture budgets are for the mock path
LIVE_BUDGET_MS = {
    "classify": 90_000,
    "reuse": 15_000,
    "compose": 120_000,
    "place": 10_000,
    "enclose": 60_000,
    "board": 240_000,
    "firmware": 30_000,
    "render": 45_000,
}
SHORT_PROMPT_WORDS = 6  # a longer product phrase is a description, not a name
# where the product's name ends and the tweaks begin
PRODUCT_END = re.compile(
    r"[,;:(]|\s(?:with|that|which|where|using|in|for|but|so|to|and|without)\s", re.IGNORECASE
)
# the ask around the product name ("create a", "can you make me an") is not part of it
REQUEST_LEAD = re.compile(
    r"^(?:(?:please|can|could|you|i|want|would|like|need|to|me|us|"
    r"create|make|build|design|generate|give|get)\b[\s,]*)+(?:(?:a|an|the|my|some)\b\s*)?",
    re.IGNORECASE,
)

MAX_CLARIFY_ROUNDS = 2

# Clarify options for a request that names no job (SPEC 8.11). Hand-set: four common desk
# gadgets the catalog can build; each adds its words to the prompt before the next brief.
FUNCTION_OPTIONS: list[dict[str, Any]] = [
    {
        "option_id": "o_keyboard",
        "label": "Be a keyboard",
        "description": "A small mechanical keyboard or macropad.",
        "words": "a small mechanical macropad keyboard",
        "implies": [],
    },
    {
        "option_id": "o_weather",
        "label": "Show the weather in the room",
        "description": "Temperature and humidity on a small screen.",
        "words": "a weather station that shows temperature and humidity on a small screen",
        "implies": [("measures", "has", "temperature", "Shows temperature and humidity")],
    },
    {
        "option_id": "o_clock",
        "label": "Be a clock",
        "description": "Time on a small display.",
        "words": "a desk clock with a small display",
        "implies": [],
    },
    {
        "option_id": "o_plant",
        "label": "Watch a plant",
        "description": "Soil moisture with a light when it needs water.",
        "words": "a plant monitor that measures soil moisture",
        "implies": [],
    },
]

# BOARD placement role -> compose slot whose instances sit on that footprint.
ROLE_SLOT = {
    "mcu": "controller",
    "battery": "battery",
    "encoder": "encoder",
    "screen": "display",
    "trackball": "trackball",
}
# Keycap seat above the PCB top when the switch record has no bbox. Hand-set from the
# MX (Cherry) and Choc v1 (Kailh) datasheets: housing top height above the board.
CAP_SEAT_MM = {"mx": 11.6, "choc": 5.8}


def _req(facet: str, op: str, value: Any, label: str, source: str) -> dict[str, Any]:
    return {
        "req_id": "r1",
        "facet": facet,
        "op": op,
        "value": value,
        "unit": None,
        "source": source,
        "text_span": None,
        "label": label,
    }


def _question(round_no: int) -> dict[str, Any]:
    options = [
        {
            "option_id": o["option_id"],
            "label": o["label"],
            "description": o["description"],
            "implies": [_req(*imp, "clarified") for imp in o["implies"]],
        }
        for o in FUNCTION_OPTIONS
    ]
    return {
        "question_id": "q_function" if round_no == 1 else f"q_function_{round_no}",
        "question": "What should it do?",
        "round": round_no,
        "options": options,
        "allow_free_text": True,
        "allow_skip": True,
        "default_option_id": "o_weather",
        "reason": "No device function in the prompt; asking instead of guessing.",
        "missing_facets": ["function"],
        "timeout_ms": 60000,
    }


def _euler_xyz(deg: list[float]) -> list[list[float]]:
    """Rotation matrix for intrinsic XYZ Euler degrees (the viewer's convention)."""
    x, y, z = (math.radians(v) for v in deg)
    cx, sx, cy, sy, cz, sz = (
        math.cos(x),
        math.sin(x),
        math.cos(y),
        math.sin(y),
        math.cos(z),
        math.sin(z),
    )
    return [
        [cy * cz, -cy * sz, sy],
        [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
        [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
    ]


def _matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _xyz_degrees(m: list[list[float]]) -> list[float]:
    y = math.asin(max(-1.0, min(1.0, m[0][2])))
    if abs(m[0][2]) < 0.9999999:
        x, z = math.atan2(-m[1][2], m[2][2]), math.atan2(-m[0][1], m[0][0])
    else:
        x, z = math.atan2(m[2][1], m[1][1]), 0.0
    return [round(math.degrees(v), 3) for v in (x, y, z)]


def _seat_on_footprints(board: dict[str, Any], parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The routed board is where a part really sits: a single-element part with one footprint
    moves onto that footprint's centre and turn, on the board's top face. Placed before routing,
    parts otherwise float where the planner left them while the board shows them elsewhere."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    for fp in board.get("footprints") or []:
        if fp.get("instance_id") and fp.get("center_mm"):
            by_id.setdefault(fp["instance_id"], []).append(fp)
    pos = board.get("position_mm") or [0.0, 0.0, 0.0]
    rb = _euler_xyz(board.get("rotation_deg") or [0.0, 0.0, 0.0])
    top = float(board.get("thickness_mm") or 1.6)
    out = []
    for part in parts:
        fps = by_id.get(part["instance_id"]) or []
        placement = part.get("placement") or {}
        if len(fps) != 1 or int(part.get("quantity") or 1) != 1 or placement.get("layout_id"):
            continue
        cx, cy = fps[0]["center_mm"]
        local = [float(cx), float(cy), top]
        world = [pos[i] + sum(rb[i][k] * local[k] for k in range(3)) for i in range(3)]
        rot = _matmul(rb, _euler_xyz([0.0, 0.0, float(fps[0].get("rot_deg") or 0.0)]))
        pl = {**placement, "position_mm": [round(v, 3) for v in world]}
        pl["rotation_deg"] = _xyz_degrees(rot)
        part["placement"] = pl
        out.append({"instance_id": part["instance_id"], "placement": pl})
    return out


SHAFT_FUNCTIONS = {"input.joystick", "input.rotary_encoder", "input.potentiometer"}


def _primary(record: dict[str, Any]) -> str:
    fns = record.get("functions") or []
    return next((f["function_id"] for f in fns if f.get("primary")), "")


def _seat_caps(
    parts: list[dict[str, Any]], moves: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """A cap (knob, keycap) is not on the board: it sits on top of the shaft part it caps.
    The host is the placed shaft part whose slot label shares the most words with the cap's
    ("Thumbstick caps" -> "Analog thumbsticks"), then the one with the same count."""
    hosts = [
        p for p in parts if p["instance_id"] in moves and _primary(p["record"]) in SHAFT_FUNCTIONS
    ]
    out = []
    for cap in parts:
        if _primary(cap.get("record") or {}) not in ("mech.knob", "mech.keycap") or not hosts:
            continue

        def words(p: dict[str, Any]) -> set[str]:
            return {w.rstrip("s") for w in str(p.get("label") or "").lower().split() if len(w) > 3}

        host = max(
            hosts,
            key=lambda h: (len(words(cap) & words(h)), h.get("quantity") == cap.get("quantity")),
        )
        hp = moves[host["instance_id"]]["placement"]
        lo, hi = _zspan(host["record"])
        pos = list(hp["position_mm"])
        flipped = abs(float(hp["rotation_deg"][0]) % 360 - 180) < 1
        pos[2] = pos[2] - (hi - lo) if flipped else pos[2] + (hi - lo)
        out.append(
            {
                "instance_id": cap["instance_id"],
                "placement": {
                    **hp,
                    "position_mm": [round(v, 3) for v in pos],
                    "explode_offset_mm": [0.0, 0.0, -25.0 if flipped else 25.0],
                },
            }
        )
    return out


def _zspan(record: dict[str, Any]) -> tuple[float, float]:
    bbox = (record.get("mechanical") or {}).get("bbox_mm") or {}
    lo, hi = bbox.get("min") or [0, 0, 0], bbox.get("max") or [0, 0, 8.0]
    return float(lo[2]), float(hi[2])


def _product_name(run: BuildRun, brief: dict[str, Any]) -> str:
    """The product the prompt names, as typed: the request words in front and the tweaks after
    it ("with", "that", a comma) cut off. "create a gameboy with a backlit screen" is "gameboy".
    The brief's device ("handheld game console") is generic, and a search for it finds lanterns."""
    product = REQUEST_LEAD.sub("", run.prompt.strip())
    product = PRODUCT_END.split(product, maxsplit=1)[0].strip(" .!?")
    product = re.sub(r"^(?:a|an|the|my|some)\s+", "", product, flags=re.IGNORECASE)
    if product and len(product.split()) <= SHORT_PROMPT_WORDS:
        return product
    return str(brief.get("device") or "") or run.prompt


def _counts(message: object) -> str:
    """The numbers in a failure message: the part of it that measures progress."""
    return ",".join(re.findall(r"\d+(?:\.\d+)?", str(message)))


class _Stage:
    """One open stage: started on enter, completed on close with its real duration."""

    def __init__(self, run: BuildRun, budget: int, stage: str, label: str) -> None:
        self.run, self.stage, self.started = run, stage, time.monotonic()
        run.emit(
            "stage.started",
            {"stage": stage, "label": label[:80], "budget_ms": budget},
            stage=stage,
        )
        self.last_progress = 0.0

    def ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def emit(self, msg_type: str, payload: dict[str, Any], **kw: Any) -> dict[str, Any]:
        kw.setdefault("stage", self.stage)
        return self.run.emit(msg_type, payload, **kw)

    def progress(self, message: str, fraction: float | None) -> None:
        if fraction is not None:
            fraction = max(self.last_progress, min(1.0, max(0.0, float(fraction))))
            self.last_progress = fraction
        self.emit(
            "stage.progress",
            {"stage": self.stage, "message": message[:200], "fraction": fraction},
        )

    def done(self, status: str = "ok", message: str | None = None) -> None:
        payload: dict[str, Any] = {"stage": self.stage, "status": status, "duration_ms": self.ms()}
        if message:
            payload["message"] = message[:200]
        self.emit("stage.completed", payload)


def _footprint_size(part: dict[str, Any]) -> tuple[float, float] | None:
    """Width and depth in mm of a part's body, from its mechanical bounding box."""
    bb = (part.get("mechanical") or {}).get("bbox_mm") or {}
    lo, hi = bb.get("min"), bb.get("max")
    if not lo or not hi:
        return None
    w, d = abs(hi[0] - lo[0]), abs(hi[1] - lo[1])
    return (round(w, 1), round(d, 1)) if w > 0 and d > 0 else None


def _spans(product: form_mod.Form, size: tuple[float, float]) -> bool:
    """True when the form already has the declared width and height (either way round)."""
    xs = [p[0] for p in product.silhouette]
    ys = [p[1] for p in product.silhouette]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    return any(abs(a - b) <= 0.1 * b for a, b in ((w, size[0]), (h, size[1]))) and any(
        abs(a - b) <= 0.1 * b for a, b in ((w, size[1]), (h, size[0]))
    )


def _form_sig(product: form_mod.Form) -> tuple[Any, ...]:
    """What a redraw can change: the outline (to the mm), the thickness and the anchors."""
    return (
        tuple((round(x), round(y)) for x, y in product.silhouette),
        round(product.thickness_mm),
        tuple(
            (a.get("slot_id"), round(float(a["centre"][0])), round(float(a["centre"][1])))
            for a in product.anchors
        ),
    )


def _measured(run: BuildRun, product: form_mod.Form | None) -> tuple[float, float, float] | None:
    """The built case's plan width, depth and height in mm (the form's when no case yet)."""
    for enc in run.state.get("enclosures") or []:
        size = enc.get("outer_size_mm")
        if size and len(size) == 3:
            return float(size[0]), float(size[1]), float(size[2])
    if product is None:
        return None
    w, h = product.size_mm
    return float(w), float(h), float(product.thickness_mm)


def _part_height(record: dict[str, Any]) -> float | None:
    """A part's own height in mm from its 3D extents or facets; None when nothing says."""
    box_ = (record.get("mechanical") or {}).get("bbox_mm") or {}
    lo, hi = box_.get("min"), box_.get("max")
    if lo and hi:
        return float(hi[2]) - float(lo[2])
    h = (record.get("facets") or {}).get("height_mm")
    return float(h) if isinstance(h, int | float) else None


def _extent(product: form_mod.Form) -> tuple[float, float, float]:
    """Overall width, height and area of the silhouette."""
    xs = [p[0] for p in product.silhouette]
    ys = [p[1] for p in product.silhouette]
    return max(xs) - min(xs), max(ys) - min(ys), Polygon(product.silhouette).area


class LiveRunner:
    def __init__(self, engine: Engine, source: PartSource) -> None:
        self.engine = engine
        self.source = as_overlay(source)
        self.catalog = engine.catalog
        self.settings = engine.settings

    def _stage(self, run: BuildRun, stage: str, label: str) -> _Stage:
        budget = LIVE_BUDGET_MS.get(stage) or self.catalog.stage_budget(stage)
        return _Stage(run, budget, stage, label)

    def _warn(self, run: BuildRun, stage: str, wid: str, code: str, sev: str, msg: str) -> None:
        used = {w["warning_id"] for w in run.state["warnings"]}
        base, n = wid, 2
        while wid in used:
            wid, n = f"{base}_{n}", n + 1
        run.emit(
            "warning",
            {
                "warning": {
                    "warning_id": wid,
                    "code": code,
                    "severity": sev,
                    "message": msg[:300],
                    "subjects": [],
                    "stage": stage,
                }
            },
            stage=stage,
        )

    # ---- entry ---------------------------------------------------------------------------
    async def run(self, run: BuildRun) -> None:
        ctx: dict[str, Any] = {}
        spec_brief = await self.classify(run)
        if spec_brief is None:
            return
        spec, brief = spec_brief
        run.device = str(brief.get("device") or "")
        plan = plan_keyboard(brief)
        await self.reuse(run, spec, brief)
        result = await self.compose(run, spec, brief, plan)
        if not result.chosen_parts:  # nothing resolved is a failed build, never an empty DONE
            why = result.error or "No part could be chosen for this request; nothing to build."
            run.emit(
                "build.failed",
                {"error": error_obj("E_CRITICAL_PART_MISSING", why, stage="compose")},
            )
            return
        merge_into_catalog(self.catalog, list(result.chosen_parts.values()))
        board = await self.place(run, brief, plan, result, ctx)
        await self.enclose(run, brief, plan, result, board, ctx)
        board = await self.board_stage(run, board, result, ctx)
        if plan is None:
            critique = await self.identity(run, ctx)
            if critique:  # one repair pass: redraw the form from the reviewer's notes
                run.repair = critique  # type: ignore[attr-defined]
                board = await self.place(run, brief, plan, result, ctx)
                await self.enclose(run, brief, plan, result, board, ctx)
                board = await self.board_stage(run, board, result, ctx)
                await self.identity(run, ctx, final=True)
        self.firmware(run, brief, plan, result, board)
        self.render(run, result, board, ctx)
        failure = await self.repair(run, brief, plan, result, board, ctx)
        self.finishing(run, brief)
        if failure is not None:
            run.emit("build.failed", {"error": failure})
            return
        run.emit("build.done", self.engine._done_payload(run, {}))

    def finishing(self, run: BuildRun, brief: dict[str, Any]) -> None:
        """After industrial design: colours and materials on purpose (clear tinted case,
        opaque controls in one palette, dark-glass screen, real board and metal finishes),
        written as `finish` on parts, boards and the case and summarised on scene.finish."""
        st = self._stage(run, "render", "Choosing colours and materials")
        msgs = finish_mod.events(run.state, list(brief.get("colours") or []))
        for msg_type, payload in msgs:
            st.emit(msg_type, payload)
        pal = ((run.state.get("scene") or {}).get("finish") or {}).get("palette_name", "")
        st.done(message=f"Clear case, {pal} palette, {len(msgs)} finishes"[:200])

    MAX_REPAIRS = 3

    async def repair(
        self,
        run: BuildRun,
        brief: dict[str, Any],
        plan: Any,
        result: ComposeResult,
        board: dict[str, Any] | None,
        ctx: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Every failing required check goes back through place, case and board with the
        failures as the repair notes, until the build passes. A round that leaves the same
        failures as one before it means the request cannot be built this way: stop and say why."""
        seen: set[tuple[tuple[str, str], ...]] = set()
        for n in range(1, self.MAX_REPAIRS + 1):
            bad = self._failing(run, (*self.REQUIRED, *self.REPAIRABLE))
            if not bad:
                return None
            # the same rules failing on the same parts is no progress, however the message
            # is worded; only a count (open connections, errors) going down is
            key = tuple(
                sorted(
                    (rid, ",".join(c.get("check_keys", [])) + "#" + _counts(c.get("message", "")))
                    for rid, c in bad
                )
            )
            if key in seen:
                break
            seen.add(key)
            notes = "; ".join(
                f"{rid}: {c.get('message', '')[:160]}"
                + (f" (fix: {c['fix']})" if c.get("fix") else "")
                for rid, c in bad
            )
            self._warn(
                run, "render", f"w_repair_{n}", "other", "info",
                f"Repair round {n}: sending back {notes}",
            )  # fmt: skip
            run.repair = f"The last attempt failed these checks; fix them: {notes}"  # type: ignore[attr-defined]
            if any(rid == "board.routing.complete" for rid, _ in bad):
                ctx["route_effort"] = n  # the router searches further, never the same input
            board = await self.place(run, brief, plan, result, ctx)
            await self.enclose(run, brief, plan, result, board, ctx)
            board = await self.board_stage(run, board, result, ctx)
            if plan is None and any(rid == "identity.reads_as_device" for rid, _ in bad):
                await self.identity(run, ctx, final=True)  # judge the redraw again
            self.firmware(run, brief, plan, result, board)
            self.render(run, result, board, ctx)
        failure = self.gate(run)
        if failure is not None:
            failure["message"] = (
                f"Could not be built after {len(seen)} repair round(s); still failing. "
                + failure["message"]
            )[:500]
        return failure

    # faults a redraw can fix (blocked access, wrong look): sent back, reported if they stay
    REPAIRABLE = ("mech.access.panel", "identity.reads_as_device")

    def _failing(
        self, run: BuildRun, rules: tuple[str, ...] | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        """Failing checks per rule, latest result per check_key: one rule can hold a check
        per part, and a later pass on one part must not hide a failure on another."""
        rules = rules or tuple(self.REQUIRED)
        latest: dict[str, dict[str, Any]] = {}
        for check in run.state["checks"]:
            latest[check.get("check_key") or check.get("rule_id") or ""] = check
        bad: dict[str, list[dict[str, Any]]] = {}
        for check in latest.values():
            rid = check.get("rule_id") or ""
            if rid in rules and check.get("status") == "fail":
                bad.setdefault(rid, []).append(check)
        return [
            (
                rid,
                {
                    **cs[0],
                    "message": " | ".join(str(c.get("message", "")) for c in cs),
                    "check_keys": sorted(str(c.get("check_key") or rid) for c in cs),
                },
            )
            for rid, cs in bad.items()
        ]

    # checks that decide whether the product exists: any one failing ends the build as failed
    FIT_REPAIRS = 2
    REQUIRED = {
        "device.complete": "E_CRITICAL_PART_MISSING",
        "slot.critical_filled": "E_CRITICAL_PART_MISSING",
        "form.valid": "E_ENCLOSURE_FAILED",
        "form.fit": "E_ENCLOSURE_FAILED",
        "board.drc": "E_BOARD_FAILED",
        "board.routing.complete": "E_BOARD_FAILED",
        "mech.fit.enclosure": "E_ENCLOSURE_FAILED",
        "mech.fit.collision": "E_ENCLOSURE_FAILED",
        "mech.fit.floating": "E_ENCLOSURE_FAILED",
        "mech.access.clipped": "E_ENCLOSURE_FAILED",
    }

    def gate(self, run: BuildRun) -> dict[str, Any] | None:
        """A failing required check is a failed build, never a clean DONE. The artefacts stay
        in the build state so the failure can be looked at."""
        bad = self._failing(run)
        if not bad:
            return None
        text = "; ".join(f"{rid}: {c.get('message', '')[:140]}" for rid, c in bad)
        return error_obj(
            self.REQUIRED[bad[0][0]], f"Build failed required checks. {text}", stage="render"
        )

    # ---- classify ------------------------------------------------------------------------
    async def classify(self, run: BuildRun) -> tuple[dict[str, Any], dict[str, Any]] | None:
        prompt = run.prompt
        resolutions: list[dict[str, Any]] = []
        clarified: list[dict[str, Any]] = []
        st = self._stage(run, "classify", "Understanding the request")
        for round_no in range(1, MAX_CLARIFY_ROUNDS + 2):
            res: BriefResult = await write_brief(
                prompt, self.catalog, self.engine.router, self.settings
            )
            self._log_brief(run, prompt, res)
            blocking = res.brief.get("blocking_facet")
            # The only question is "what should it do"; skip it once the brief names a job
            # (input, display, sensing...), not just support parts like a case or an MCU.
            support = ("mech.", "interconnect.", "power.", "compute.", "comms.")
            if blocking and any(not f.startswith(support) for f in res.brief.get("functions", [])):
                blocking = res.brief["blocking_facet"] = None
            if blocking and res.brief["scope"] == "in_scope":
                # a named device implies its job: the block diagram answers what the brief could not
                got, _ = await blocks_mod.derive(run.prompt, self.catalog.function_ids())
                if got is not None:
                    run.live_blocks = got  # type: ignore[attr-defined]
                    blocking = res.brief["blocking_facet"] = None
                    msg = "The request names no function; built the usual "
                    msg += f"{got['device_class']} from its function block diagram."
                    self._warn(run, "classify", "w_blocking", "assumption_made", "warning", msg)
            if not blocking or round_no > MAX_CLARIFY_ROUNDS or res.brief["scope"] != "in_scope":
                break
            st.done("needs_input", "The request names no function; asking instead of guessing.")
            question = _question(round_no)
            run.emit("clarify.request", question)
            resolution = await self.engine._wait_clarify(run, question)
            msg_id = resolution.pop("_msg_id", None)
            run.emit("clarify.resolved", resolution, cause={"msg_id": msg_id} if msg_id else None)
            resolutions.append({"question": question, "resolution": resolution})
            option = self.engine._option(question, resolution.get("option_id"))
            spec_opt = next(
                (o for o in FUNCTION_OPTIONS if o["option_id"] == resolution.get("option_id")),
                FUNCTION_OPTIONS[1],
            )
            words = resolution.get("free_text") or spec_opt["words"]
            if resolution["resolution"] == "answered_option":
                words = spec_opt["words"]
            prompt = f"{run.prompt}: {words}"
            assumed = resolution["resolution"] in ("skipped", "timeout")
            for req in (option or {}).get("implies", []):
                req = copy.deepcopy(req)
                req["source"] = "assumed" if assumed else "clarified"
                clarified.append(req)
            st = self._stage(run, "classify", "Understanding the request")
        for warning in res.warnings:
            run.emit("warning", {"warning": copy.deepcopy(warning)}, stage="classify")
        assumptions = [a for r in resolutions for a in r["resolution"].get("assumptions", [])]
        if res.brief["scope"] != "in_scope" and await completeness.low_voltage_mains(run.prompt):
            # A charger or power strip is built as its low-voltage half around a certified
            # AC-DC module; the mains side is never ours (see the safety.mains_wiring check).
            res.brief["scope"] = "in_scope"
            res.brief["blocking_facet"] = None
            res.brief["device_class"] = (
                res.brief.get("device_class")
                if res.brief.get("device_class") not in (None, "other")
                else "other"
            )
            self._warn(
                run,
                "classify",
                "w_mains",
                "assumption_made",
                "warning",
                "Mains device: built as the low-voltage half around a certified AC-DC module; "
                "the mains side is the module's job.",
            )
        if res.brief["scope"] == "in_scope":
            res.brief = await self.understand(run, prompt, res.brief, st)
            arch = archetype.apply(
                prompt, res.brief, self.source, self.settings.data_dir / "archetypes.json"
            )
            res.brief = normalise_brief(res.brief, self.catalog)
            run.live_archetype = arch  # type: ignore[attr-defined]
        spec = spec_from_brief(
            run.prompt, res.brief, res.classifier, assumptions=assumptions, clarified=clarified
        )
        if res.brief["scope"] != "in_scope":
            spec["scope"] = "out_of_scope"
            spec["scope_reason"] = (
                f"Bara builds small electronic gadgets; {res.brief.get('device') or 'this'} "
                "is not one."
            )[:200]
            st.emit("spec.ready", {"spec": spec})
            st.done()
            run.emit(
                "build.failed",
                {"error": error_obj("E_OUT_OF_SCOPE", spec["scope_reason"], stage="classify")},
            )
            return None
        st.emit("spec.ready", {"spec": spec})
        if resolutions:
            self.engine._emit_assumption_warnings(run, resolutions, "classify", None)
        st.done()
        run.live_brief = res.brief  # type: ignore[attr-defined]
        return spec, res.brief

    async def understand(
        self, run: BuildRun, prompt: str, brief: dict[str, Any], st: _Stage
    ) -> dict[str, Any]:
        """Retrieve real references for this kind of device, then have the model write the
        device concept from them: what it is, its form, layout and parts, and which build path
        fits. The concept is a reading grounded in what was retrieved, never a fixed label."""
        st.progress("Retrieving real products and open designs of this device", 0.5)
        # a generic product class, never a brand or a model name the request may have typed
        ret = await retrieval.gather(str(brief.get("device") or "") or _product_name(run, brief))
        run.retrieval = ret  # type: ignore[attr-defined]
        run.web_photos = ret.photos  # type: ignore[attr-defined]
        run.web_sources = ret.photo_sources  # type: ignore[attr-defined]
        st.progress("Working out what the device is from the references", 0.7)
        concept, note = await concept_mod.derive(
            prompt, self.catalog.function_ids(), self.catalog.device_classes(), brief, ret
        )
        run.device_concept = concept  # type: ignore[attr-defined]
        log.info(
            "device concept %s (%s; %s): %s",
            run.build_id, note, "; ".join(ret.notes), json.dumps(concept, sort_keys=True),
        )  # fmt: skip
        if concept is None:
            self._warn(
                run, "classify", "w_concept", "llm_degraded", "warning",
                f"No device concept ({note}); the brief's own reading picks the build path.",
            )  # fmt: skip
            return brief
        path = "keyboard pipeline" if concept_mod.is_keyboard(concept) else "device path"
        self._warn(
            run, "classify", "w_concept", "assumption_made", "info",
            f"Read as a {concept['device_name']} ({path}: {concept['build_path_reason']}) from "
            f"{len(ret.designs)} open design(s), {len(ret.pages)} page(s), "
            f"{len(ret.photos)} photo(s).",
        )  # fmt: skip
        return concept_mod.apply(brief, concept)

    def _log_brief(self, run: BuildRun, prompt: str, res: BriefResult) -> None:
        record = {"build_id": run.build_id, "prompt": prompt, "brief": res.brief,
                  "classifier": res.classifier}  # fmt: skip
        log.info("live brief %s: %s", run.build_id, json.dumps(record, sort_keys=True))
        try:
            out = self.settings.data_dir / "cache" / "briefs"
            out.mkdir(parents=True, exist_ok=True)
            with (out / f"{run.build_id}.jsonl").open("a") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            log.warning("live: could not write the brief log for %s", run.build_id)

    # ---- reuse ---------------------------------------------------------------------------
    async def reuse(self, run: BuildRun, spec: dict[str, Any], brief: dict[str, Any]) -> None:
        st = self._stage(run, "reuse", "Looking for an existing open design")
        reqs = spec["hard_requirements"]
        by_facet = {r["facet"]: r["req_id"] for r in reqs}
        considered = []
        for design in self.source.designs():
            if design.get("device_class") != spec["device_class"]:
                continue
            unmet = [by_facet[f] for f in self.engine.router.changes_needed(design, reqs)]
            score = round(1.0 - len(unmet) / max(1, len(reqs)) * 0.8, 2)
            considered.append(
                {
                    "design_id": design["design_id"],
                    "name": design.get("name") or design["design_id"],
                    "tier": "compose",
                    "score": score,
                    "unmet": unmet,
                }
            )
        considered.sort(key=lambda d: -d["score"])
        arch = getattr(run, "live_archetype", None)
        design_id = None
        if arch is not None and arch.archetype is not None:
            design_id = arch.archetype["id"]
            top_arch = max((sc for sc, _ in arch.considered), default=1.0) or 1.0
            arch_rows = [
                {
                    "design_id": a["id"],
                    "name": a["name"][:80],
                    "tier": "compose",
                    "score": round(min(1.0, sc / top_arch), 2),
                    "unmet": [],
                }
                for sc, a in arch.considered[:3]
            ]
            seen_ids = {r["design_id"] for r in arch_rows}
            considered = arch_rows + [d for d in considered if d["design_id"] not in seen_ids]
            reason = arch.reason() + " New KiCad board, case and firmware generated."
        else:
            reason = "No archetype matched; generating a new KiCad board, case and firmware."
        st.progress("Searching open KiCad projects", 0.2)
        found, note = await open_designs.search(_product_name(run, brief))
        scouted = open_designs.rows(run.prompt, str(brief.get("device") or ""))
        seen = {r["design_id"] for r in scouted}
        opens = scouted + [r for r in open_designs.to_rows(found, 5) if r["design_id"] not in seen]
        opens = sorted(opens, key=lambda r: -r["score"])[:5]
        run.open_designs = found  # type: ignore[attr-defined]
        log.info("open designs for %s: %d searched (%s)", run.build_id, len(found), note)
        if opens:
            considered = opens + considered
            reason += f" Closest open design: {opens[0]['name']}, compared only."
        else:
            reason += f" No open KiCad project found for this device ({note})."
        st.emit(
            "reuse.decided",
            {
                "tier": "compose",
                "design_id": design_id,
                "design": None,
                "considered": considered[:5],
                "unmet_hard": [],
                "reason": reason[:240],
            },
        )
        st.done()

    REFERENCE_BUDGET_S = 25.0

    async def _reference_design(self, run: BuildRun, st: Any, composer: Composer) -> None:
        """Match the open KiCad projects the build already retrieved against its function
        blocks; a reusable match's footprints are preferred when parts are chosen, and the
        project is recorded with its licence."""
        ret = getattr(run, "retrieval", None)
        designs = list(getattr(ret, "designs", None) or [])
        if not designs:
            return
        st.progress("Matching open reference designs by function block", None)
        try:
            ref = await asyncio.wait_for(
                reference_mod.match(designs, [s.function_id for s in composer.slots]),
                self.REFERENCE_BUDGET_S,
            )
        except TimeoutError:
            ref = None
        run.reference_design = ref.json() if ref else None  # type: ignore[attr-defined]
        if ref is None:
            return
        composer.reference_fps = reference_mod.preferred(ref)  # type: ignore[attr-defined]
        if composer.reference_fps:  # type: ignore[attr-defined]
            how = "its footprints are preferred for those blocks."
        elif not ref.reusable:
            how = "compared only (its licence does not allow reuse)."
        else:
            how = "compared only (too few blocks in common)."
        self._warn(
            run, "compose", "w_reference", "other", "info",
            f"Reference design {ref.repo} ({ref.licence}) builds {len(ref.matched)} of this "
            f"device's function blocks ({ref.coverage:.0%}); {how}",
        )  # fmt: skip

    def _write_chain(self, run: BuildRun, record: dict[str, Any]) -> None:
        """Keep the jobs -> functions -> blocks -> parts chain next to the build's artefacts."""
        out = self.settings.data_dir / "cache" / "chains"
        out.mkdir(parents=True, exist_ok=True)
        record = {**record, "reference_design": getattr(run, "reference_design", None)}
        (out / f"{run.build_id}.json").write_text(json.dumps(record, indent=1))

    # ---- compose -------------------------------------------------------------------------
    async def compose(
        self,
        run: BuildRun,
        spec: dict[str, Any],
        brief: dict[str, Any],
        plan: KeyboardPlan | None,
    ) -> ComposeResult:
        st = self._stage(run, "compose", "Choosing parts")
        controllers = A.board_controllers() if plan is not None else {}
        blocks = getattr(run, "live_blocks", None)
        if plan is None and blocks is None:
            for _ in range(2):  # the diagram sets every part and quantity; one retry on failure
                blocks, note = await blocks_mod.derive(
                    run.prompt,
                    self.catalog.function_ids(),
                    concept_mod.concept_text(getattr(run, "device_concept", None)),
                )
                if blocks is not None:
                    break
            if blocks is None:  # no silent defaults: guessed parts and counts are not a design
                msg = f"The function block diagram could not be derived ({note}); nothing built."
                st.done()
                return ComposeResult(slots=[], error=msg)
        run.live_blocks = blocks  # type: ignore[attr-defined]
        composer = Composer(
            self.source, spec, brief, plan, self.settings, controllers, blocks=blocks
        )
        st.emit("slots.ready", {"slots": [s.json() for s in composer.slots]})
        await self._reference_design(run, st, composer)
        if plan is not None:
            for half in plan.halves:
                lid = {"left": "lay_l", "right": "lay_r"}.get(half.side, "lay_main")
                name = f"{plan.key_count} key {plan.style}" + (
                    f" {half.side}" if half.side != "none" else ""
                )
                st.emit("layout.added", {"layout": plan.layout_json(half, lid, name)})
        result = await composer.run(st.emit, st.progress)
        record = blocks_mod.chain(blocks, composer.slots, composer.comp.dropped)
        run.use_case_chain = record  # type: ignore[attr-defined]
        uc = record["use_case"] or {}
        jobs = "; ".join(uc.get("jobs") or [])
        unresolved = sum(1 for k in record["links"] if k["outcome"].startswith("UNRESOLVED"))
        tail = f" -> {len(record['links'])} blocks, {unresolved} unresolved"
        room = 120 - len("use case: ") - len(tail)  # stage.progress message maxLength
        head = jobs if len(jobs) <= room else jobs[: room - 3].rstrip() + "..."
        st.progress(f"use case: {head}{tail}", None)
        self._write_chain(run, record)
        checks = composer.checks()
        if checks:
            st.emit("check.result", {"results": checks})
        result.log += plan.log if plan else []
        run.live_composer = composer  # type: ignore[attr-defined]
        st.done()
        return result

    # ---- place (KiCad board build) -------------------------------------------------------
    async def place(
        self,
        run: BuildRun,
        brief: dict[str, Any],
        plan: KeyboardPlan | None,
        result: ComposeResult,
        ctx: dict[str, Any],
    ) -> dict[str, Any] | None:
        slots = {s.slot_id: s for s in result.slots}
        if plan is None:
            return await self._place_generic(run, brief, result, ctx)

        st = self._stage(run, "place", "Placing parts on a KiCad board")
        ctrl = slots.get("controller")
        mcu_label = (ctrl.chosen or {}).get("display_name") if ctrl else None
        bb = A.board_brief(brief, mcu_label, plan)
        board, err = await asyncio.to_thread(A.plan_board, bb, result.parts, run.build_id)
        if board is None:
            self._warn(run, "place", "w_board", "other", "warning", f"No KiCad board: {err}")
            # The case still follows the key grid: one plain outline per half, no routing.
            ctx["records"] = [A.plan_outline(half, plan.style) for half in plan.halves]
            ctx["board_err"] = err
            st.done("degraded", err)
            return None
        self._controller_check(run, st, result, board)
        pitch = A.key_pitch(brief.get("switch_family"))
        moves: list[dict[str, Any]] = []
        records = []
        for entry in board["boards"]:
            if entry["name"].endswith("sensor"):
                continue
            records.append(A.geometry_board(entry))
            side = entry.get("side") or "none"
            lid = {"left": "lay_l", "right": "lay_r"}.get(side, "lay_main")
            keys = [
                {
                    "x": p["x_mm"],
                    "y": p["y_mm"],
                    "rot": p["rot_deg"],
                    "w_u": p.get("w_u", 1.0),
                    "matrix": p.get("matrix"),
                }
                for p in entry["placements"]
                if p["role"] == "switch"
            ]
            half = next((h for h in plan.halves if h.side == side), plan.halves[0])
            if keys:
                # the board's electrical matrix is the one firmware must scan
                for k, src in zip(keys, half.keys, strict=False):
                    if k["matrix"] is None:
                        k["matrix"] = src.get("matrix")
                    src["matrix"] = k["matrix"]
                budget = entry.get("pin_budget") or {}
                if budget.get("rows") and budget.get("cols"):
                    half.elec_matrix = (int(budget["rows"]), int(budget["cols"]))
                name = f"{plan.key_count} key {plan.style} (KiCad)" + (
                    f" {side}" if side != "none" else ""
                )
                layout, origin = A.layout_from_keys(keys, lid, name, pitch)
                st.emit("layout.added", {"layout": layout})
                ctx.setdefault("layout_origin", {})[side] = origin
            moves += self._moves(entry, side, origin if keys else [0, 0, 0], slots, brief)
        ctx["records"] = records
        if moves:
            st.emit("placement.updated", {"placements": moves})
        ctx["moves"] = {m["instance_id"]: m for m in moves}
        # Parts BOARD already placed as footprints (keycaps included as role "keycap");
        # GEOMETRY must not get them twice or they collide with themselves.
        knobs = {i.instance_id for i in slots["knob"].instances} if "knob" in slots else set()
        ctx["on_board"] = set(ctx["moves"]) - knobs
        st.done()
        return board

    @staticmethod
    def _touches(result: ComposeResult) -> list[form_mod.Touch]:
        """Slots a person touches, sees or plugs into: the form stage gives each an anchor."""
        out = []
        for slot in result.slots:
            if slot.chosen is None or not slot.quantity:
                continue
            fid = slot.function_id
            plain = fid.split(".")[0] in ("input", "output", "display") or fid == "power.usb_in"
            if (slot.need is not None and slot.need.touch) or (slot.need is None and plain):
                groups = slot.need.groups if slot.need is not None else ()
                out.append(
                    form_mod.Touch(
                        slot.slot_id,
                        slot.label,
                        fid,
                        max(1, slot.quantity),
                        groups,
                        _footprint_size(slot.chosen),
                    )
                )
        return out

    async def _photos(self, run: BuildRun) -> list[bytes]:
        """Web pictures of this kind of device (its generic class plus "3d model"), searched once
        per build and shared by the form and the identity judge as visual reference only."""
        if not hasattr(run, "web_photos"):
            brief = getattr(run, "live_brief", None) or {}
            # the brief's generic device class, never a brand or model name the request typed
            kind = str(brief.get("device") or "") or _product_name(run, brief)
            photos, sources, note = await websearch.reference_photos(kind)
            run.web_photos = photos  # type: ignore[attr-defined]
            run.web_sources = sources  # type: ignore[attr-defined]
            log.info("web reference photos for %s: %d (%s)", run.build_id, len(photos), note)
        return run.web_photos  # type: ignore[attr-defined]

    async def form_stage(
        self,
        run: BuildRun,
        result: ComposeResult,
        st: _Stage,
        fit: dict[str, Any] | None = None,
    ) -> form_mod.Form | None:
        """The product's silhouette and anchors, from the model grounded on reference designs."""
        touches = self._touches(result)
        st.progress("Designing the product form", 0.0)
        previous = getattr(run, "product_form", None)
        repair = getattr(run, "repair", "")
        floor = getattr(run, "fit_floor", None)
        if repair and not fit and floor:  # the parts need this much: change the shape within it
            repair += (
                f"\nHard constraint: the parts only fit a form at least {floor[0]:.0f} x "
                f"{floor[1]:.0f} mm overall with at least {floor[2]:.0f} mm2 of area. Keep every "
                f"dimension and the area at or above that; change only the shape within it."
            )
        photos = await self._photos(run)
        product, note = await form_mod.derive(
            run.prompt, touches, previous if (repair or fit) else None, repair, fit, photos,
            concept=concept_mod.concept_text(getattr(run, "device_concept", None)),
        )  # fmt: skip
        if repair and not fit and floor and product is not None and previous is not None:
            w, h, area = _extent(product)
            if w < 0.98 * floor[0] or h < 0.98 * floor[1] or area < 0.97 * floor[2]:
                self._warn(
                    run, "place", "w_floor", "assumption_made", "info",
                    f"Identity redraw {w:.0f} x {h:.0f} mm is below the fit floor "
                    f"{floor[0]:.0f} x {floor[1]:.0f} mm; the form that fits was kept.",
                )  # fmt: skip
                product = previous
        run.product_form = product  # type: ignore[attr-defined]
        if (repair or fit) and previous is not None and product is not None:
            self._warn(
                run,
                "place",
                "w_form_repair",
                "assumption_made",
                "info",
                ("Fit repair resized the form: " if fit else "Identity repair redrew the form: ")
                + form_mod.diff(previous, product),
            )
        problems = list(product.problems) if product is not None else [f"no form ({note})"]
        poly_ok = product is not None and Polygon(product.silhouette).is_valid
        result.log.append("form: " + (product.summary() if product is not None else note))
        st.emit(
            "check.result",
            {
                "results": [
                    {
                        "check_key": "form.valid",
                        "rule_id": "form.valid",
                        "status": "fail" if problems else "pass",
                        "severity": "error",
                        "message": (
                            "Product form: " + "; ".join(problems)
                            if problems
                            else f"Silhouette {product.summary()}"  # type: ignore[union-attr]
                        )[:300],
                        "subjects": [],
                        "stage": "place",
                    }
                ]
            },
        )
        return product if poly_ok else None

    async def identity(self, run: BuildRun, ctx: dict[str, Any], final: bool = False) -> str | None:
        """Render the hero view and ask whether it reads as the requested device. Returns the
        reviewer's critique when it does not (and this is not already the repair pass)."""
        product = getattr(run, "product_form", None)
        touch_slots = list((getattr(run, "touch_slots", None)) or [])
        st = self._stage(run, "render", "Checking that it looks like the device")
        recs = [(rec, False) for rec in run.state["enclosures"]] + [
            (rec, True) for rec in run.state["boards"]
        ]
        root = self.settings.assets_dir
        meshes: list[hero.Mesh] = []
        for rec, is_board in recs:
            pose = (
                hero.pose_matrix(rec.get("position_mm") or [0, 0, 0], rec.get("rotation_deg"))
                if is_board
                else None
            )
            for a in rec.get("assets", []):
                if a.get("kind") != "glb" or not a.get("url"):
                    continue
                path = root / a["url"].removeprefix("/assets/")
                if path.is_file():
                    plain = await asyncio.to_thread(hero.plain_copy, path, root / "cache" / "hero")
                    if plain is not None:
                        meshes += await asyncio.to_thread(hero.load_glb, plain, 1000.0, pose)
        # the parts a person sees or touches, seated where the build puts them (never exploded)
        for part in run.state["parts"]:
            pl = part.get("placement") or {}
            if pl.get("mode") == "layout" or part.get("side") not in ("none", None):
                continue
            pose = hero.pose_matrix(pl.get("position_mm") or [0, 0, 0], pl.get("rotation_deg"))
            for a in part.get("assets", []):
                if a.get("kind") != "glb" or not a.get("url"):
                    continue
                path = root / a["url"].removeprefix("/assets/")
                if path.is_file() and part.get("slot_id") in set(touch_slots):
                    plain = await asyncio.to_thread(hero.plain_copy, path, root / "cache" / "hero")
                    if plain is not None:
                        meshes += await asyncio.to_thread(hero.load_glb, plain, 1000.0, pose)
                    break
        verdict: dict[str, Any] | None = None
        note = "no form" if product is None else "nothing to render"
        # a redraw that left the form as it was, or a re-judge that objects to the same things,
        # cannot converge: the earlier verdict and message stand (so a repair round that sends
        # it back sees the same failure and stops) instead of judging and redrawing again
        last = getattr(run, "identity_last", None)
        sig = _form_sig(product) if product is not None else None
        stuck = bool(
            final and last and not last["ok"] and (last["sig"] == sig or last.get("stuck"))
        )
        if stuck and last:
            verdict, note = last["verdict"], "unchanged"
        elif product is not None and meshes:
            if product.rest_pose == "upright":
                meshes = hero.stand_up(meshes)
            eye, target = hero.hero_camera(meshes, product.rest_pose)
            png = await asyncio.to_thread(hero.render, meshes, eye, target)
            out = root / "cache" / "hero"
            out.mkdir(parents=True, exist_ok=True)
            run.hero_png = out / f"{run.build_id}{'_repaired' if final else ''}.png"  # type: ignore[attr-defined]
            run.hero_png.write_bytes(png)  # type: ignore[attr-defined]
            verdict, note = await identity_mod.judge(
                run.prompt,
                product.description,
                product.reference,
                png,
                await self._photos(run),
                device_class=str(product.device_class or getattr(run, "device", "") or ""),
                measured=_measured(run, product),
            )
            if (
                final
                and last
                and not last["ok"]
                and verdict is not None
                and not verdict["reads_as_device"]
                and identity_mod.same_objection(last["verdict"], verdict)
            ):
                stuck = True
        run.identity = verdict  # type: ignore[attr-defined]
        ok = verdict is not None and bool(verdict["reads_as_device"])
        message = (
            f"Reads as the device: {verdict['sees']}"
            if ok and verdict
            else (
                f"Does not read as the requested device: {verdict['sees']}"
                if verdict
                else f"Identity not judged ({note})"
            )
        )
        if verdict and not ok and verdict["mismatches"]:
            message += " | " + "; ".join(verdict["mismatches"])
        if stuck and last:
            message = last["message"]
            if not last.get("stuck"):
                self._warn(
                    run, "render", "w_identity_stuck", "other", "warning",
                    "The redraw did not change what the look reviewer objected to; no further "
                    "identity redraws. Last verdict: " + message[:200],
                )  # fmt: skip
        run.identity_last = {  # type: ignore[attr-defined]
            "sig": sig,
            "ok": ok,
            "verdict": verdict,
            "message": message,
            "stuck": stuck,
        }
        st.emit(
            "check.result",
            {
                "results": [
                    {
                        "check_key": "identity.reads_as_device",
                        "rule_id": "identity.reads_as_device",
                        "status": "pass" if ok else ("fail" if verdict else "unknown"),
                        # a look judgement: reported and repaired once, never a reason to
                        # withhold a board and case that pass every physical check
                        "severity": "warning",
                        "message": message[:300],
                        "subjects": [],
                        "stage": "render",
                    }
                ]
            },
        )
        st.done()
        if verdict is not None and not ok and not final:
            return identity_mod.critique(verdict, _measured(run, product))
        return None

    def _form_fit_check(
        self, run: BuildRun, st: _Stage, board: dict[str, Any], product: form_mod.Form
    ) -> None:
        over = [line for line in board.get("log", []) if line.startswith("FORM_OVERFLOW")]
        grown = [line for line in board.get("log", []) if "grown" in line and "silhouette" in line]
        st.emit(
            "check.result",
            {
                "results": [
                    {
                        "check_key": "form.fit",
                        "rule_id": "form.fit",
                        "status": "fail" if over else "pass",
                        "severity": "error",
                        "message": (
                            over[0] if over else (grown[0] if grown else "Parts fit the silhouette")
                        )[:300],
                        "subjects": [],
                        "stage": "place",
                    }
                ]
            },
        )

    WALL_STACK_MM = 3.0  # case wall above and below the stack
    STACK_CLEARANCE_MM = 1.0

    def _thicken_to_stack(
        self, run: BuildRun, st: Any, brief: dict[str, Any], board: dict[str, Any], product: Any
    ) -> None:
        """The body is at least as thick as the real stack: the board, the tallest part on each
        side (off-board modules count by their own thickness) and a wall on each face."""
        stack, tall = self._stack_mm(board)
        top, bottom = tall["top"][1], tall["bottom"][1]
        if stack > product.thickness_mm:
            self._warn(
                run, "place", "w_stack", "other", "info",
                f"Body thickened {product.thickness_mm:.0f} -> {stack:.0f} mm: the parts stack "
                f"{top:.1f} mm above and {bottom:.1f} mm below the board.",
            )  # fmt: skip
            brief["body_thickness_mm"] = stack

    def _stack_mm(self, board: dict[str, Any]) -> tuple[float, dict[str, tuple[str, float]]]:
        """The body thickness the parts need (board, tallest part on each side, a wall on each
        face) and, per side, the tallest placed part as (instance id, height)."""
        tall: dict[str, tuple[str, float]] = {"top": ("", 0.0), "bottom": ("", 0.0)}
        thick = 1.6
        for entry in board["boards"]:
            thick = float(entry.get("thickness_mm") or thick)
            for pl in entry["placements"]:
                h = float(pl.get("height_mm") or 0.0)
                side = "bottom" if pl.get("side") == "bottom" else "top"
                if h > tall[side][1]:
                    tall[side] = (str(pl.get("for_instance_id") or ""), h)
        stack = (
            tall["top"][1] + thick + tall["bottom"][1]
            + 2 * self.WALL_STACK_MM + self.STACK_CLEARANCE_MM
        )  # fmt: skip
        return stack, tall

    THICK_SLACK = 1.4  # a stack this much over the product's own thickness is a part problem

    async def _swap_to_thickness(
        self,
        run: BuildRun,
        st: Any,
        gb: dict[str, Any],
        result: ComposeResult,
        parts: list[dict[str, Any]],
        board: dict[str, Any] | None,
        err: str | None,
        product: form_mod.Form | None,
    ) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
        """A part whose height alone would make the body far thicker than the product is
        swapped for its slot's best candidate that stands lower (a pouch cell for a 9 V clip),
        before the body is thickened round it: the product keeps its real proportions."""
        composer = getattr(run, "live_composer", None)
        for _ in range(self.MAX_SWAPS):
            if composer is None or board is None or product is None:
                break
            stack, tall = self._stack_mm(board)
            budget = max(product.thickness_mm * self.THICK_SLACK, product.thickness_mm + 4.0)
            iid, h = max(tall.values(), key=lambda t: t[1])
            if stack <= budget or not iid:
                break
            old = next((p for p in parts if p.get("instance_id") == iid), None)
            area = None
            if old is not None:
                ext = board_footprint_mm(old.get("record") or {})
                area = ext[0] * ext[1] if ext else None

            def fits(cand: dict[str, Any], h: float = h, area: float | None = area) -> bool:
                try:
                    record = self.source.get_part(cand["part_id"])
                except Exception:  # noqa: BLE001 - a part the source cannot serve is not a fit
                    return False
                hh = _part_height(record)
                ext = board_footprint_mm(record)
                if area is not None and ext is not None and ext[0] * ext[1] > 1.5 * area:
                    return False
                return hh is None or hh < h - 1.0

            why = f"{h:.0f} mm tall, the product is {product.thickness_mm:.0f} mm thick"
            part = composer.resize(iid, fits, why, st.emit)
            if part is None:
                break
            label = (old or {}).get("label") or iid
            self._warn(
                run, "place", f"w_thin_{part['part_id']}"[:60], "other", "info",
                f"{label} ({why}) swapped for {part.get('display_name') or part['part_id']}.",
            )  # fmt: skip
            parts = []
            for p in result.parts:
                try:
                    record = self.source.get_part(p["part_id"])
                except Exception:  # a part the source no longer has stays off the board
                    record = {}
                parts.append({**p, "record": record})
            board, err = await asyncio.to_thread(A.plan_board, gb, parts, run.build_id)
        return board, err, parts

    MAX_SWAPS = 3

    async def _swap_to_fit(
        self,
        run: BuildRun,
        st: Any,
        gb: dict[str, Any],
        result: ComposeResult,
        parts: list[dict[str, Any]],
        board: dict[str, Any] | None,
        err: str | None,
    ) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
        """A part with no free spot in the product is swapped for its slot's best candidate
        with a smaller footprint (or none: wired off the board, under it) before the product is
        redrawn bigger: the form stays what was asked for, the part follows the volume."""
        composer = getattr(run, "live_composer", None)
        for _ in range(self.MAX_SWAPS):
            report = (gb.get("product_form") or {}).get("fit_report") or {}
            stuck = report.get("stuck")
            if composer is None or board is None or report.get("ok", True) or not stuck:
                break
            longest, area = max(stuck["mm"]), float(stuck["mm2"])

            def fits(cand: dict[str, Any], longest: float = longest, area: float = area) -> bool:
                try:
                    record = self.source.get_part(cand["part_id"])
                except Exception:  # noqa: BLE001 - a part the source cannot serve is not a fit
                    return False
                ext = board_footprint_mm(record)
                if ext is None:  # off the board: its own body must still be smaller
                    box_ = (record.get("mechanical") or {}).get("bbox_mm") or {}
                    lo, hi = box_.get("min"), box_.get("max")
                    if not (lo and hi):
                        return True
                    ext = (hi[0] - lo[0], hi[1] - lo[1])
                return max(ext) < longest and ext[0] * ext[1] < area

            mm = "x".join(f"{v:.0f}" for v in stuck["mm"])
            why = f"{mm} mm, no free spot in the product"
            part = composer.resize(str(stuck["instance_id"]), fits, why, st.emit)
            if part is None:
                break
            self._warn(
                run, "place", f"w_swap_{part['part_id']}"[:60], "other", "info",
                f"{stuck['part']} ({mm} mm) does not fit the product; swapped for "
                f"{part.get('display_name') or part['part_id']}.",
            )  # fmt: skip
            parts = []
            for p in result.parts:
                try:
                    record = self.source.get_part(p["part_id"])
                except Exception:  # a part the source no longer has stays off the board
                    record = {}
                parts.append({**p, "record": record})
            board, err = await asyncio.to_thread(A.plan_board, gb, parts, run.build_id)
        return board, err, parts

    async def _place_generic(
        self, run: BuildRun, brief: dict[str, Any], result: ComposeResult, ctx: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Any device: the chosen parts' own KiCad footprints on one routed board."""
        st = self._stage(run, "place", "Placing parts on a KiCad board")
        parts = []
        for p in result.parts:
            try:
                record = self.source.get_part(p["part_id"])
            except Exception:  # a part the source no longer has stays off the board
                record = {}
            parts.append({**p, "record": record})
        gb = {
            "generic": True,
            "form": brief.get("form"),
            "touch_slots": [t.slot_id for t in self._touches(result)],
        }
        run.touch_slots = gb["touch_slots"]  # type: ignore[attr-defined]
        product = await self.form_stage(run, result, st)
        if product is not None:
            gb["product_form"] = product.json()
            brief["body_thickness_mm"] = product.thickness_mm
            brief["edge_thickness_mm"] = product.edge_thickness_mm
            brief["anchors"] = product.anchors
            brief["shape_features"] = product.features
        board, err = await asyncio.to_thread(A.plan_board, gb, parts, run.build_id)
        board, err, parts = await self._swap_to_fit(run, st, gb, result, parts, board, err)
        board, err, parts = await self._swap_to_thickness(
            run, st, gb, result, parts, board, err, product
        )
        grown = False
        for _ in range(
            1 if getattr(run, "repair", "") else self.FIT_REPAIRS
        ):  # one fit pass after an identity redraw; else a form too small is redrawn with numbers
            report = (gb.get("product_form") or {}).get("fit_report")
            if product is None or board is None or not report or report["ok"]:
                break
            declared = form_mod.declared_size(run.prompt)
            if declared:  # the request fixes the size: the parts must fit it or the build fails
                report = {**report, "declared_mm": list(declared)}
                if _spans(product, declared):
                    break
            redrawn = await self.form_stage(run, result, st, fit=report)
            if redrawn is None or redrawn.problems:
                break
            product = redrawn
            grown = True
            gb["product_form"] = product.json()
            brief["body_thickness_mm"] = product.thickness_mm
            brief["edge_thickness_mm"] = product.edge_thickness_mm
            brief["anchors"] = product.anchors  # the case opens where the redrawn form says
            brief["shape_features"] = product.features
            board, err = await asyncio.to_thread(A.plan_board, gb, parts, run.build_id)
        report = (gb.get("product_form") or {}).get("fit_report")
        if product is not None and report and report["ok"]:
            w, h, area = _extent(product)
            if not grown:  # no redraw proved a size: the floor is what the footprints need
                need = report["parts_mm2"] / (1.2 * max(1, report["usable_mm2"]))
                w, h = max(report["widest_mm"] + 7.0, 0.0), 0.0
                area *= min(1.0, need)
            run.fit_floor = (w, h, area)  # type: ignore[attr-defined]
        if product is not None and board is not None:
            self._thicken_to_stack(run, st, brief, board, product)
            self._form_fit_check(run, st, board, product)
        if board is None or not any(
            pl.get("for_instance_id") for e in board["boards"] for pl in e["placements"]
        ):
            err = err or "no chosen part has a KiCad footprint"
            self._warn(run, "place", "w_board", "other", "warning", f"No KiCad board: {err}")
            record = A.parts_board(result.parts, self.catalog.parts)
            ctx["records"] = [record]
            ctx["on_board"] = {p["instance_id"] for p in record["placements"]}
            ctx["board_err"] = err
            st.done("degraded", f"No KiCad board ({err}); parts laid out on a plain carrier.")
            return None
        entry = board["boards"][0]
        ctx["records"] = [A.geometry_board(entry)]
        t = float(entry.get("thickness_mm") or 1.6)
        moves: list[dict[str, Any]] = []
        seen: set[str] = set()
        for pl in entry["placements"]:
            iid = pl.get("for_instance_id")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            pos = list(pl["placement"]["position_mm"])
            pos[2] = t + pos[2] if pos[2] >= 0 else pos[2] - 3.0
            moves.append(
                {
                    "instance_id": iid,
                    "placement": {
                        "mode": "single",
                        "position_mm": [round(v, 3) for v in pos],
                        "rotation_deg": [round(v, 3) for v in pl["placement"]["rotation_deg"]],
                        "explode_offset_mm": [0.0, 0.0, 15.0 if pos[2] >= 0 else -15.0],
                        "source": "solver",
                        "locked": False,
                    },
                }
            )
        moves += _seat_caps(parts, {m["instance_id"]: m for m in moves})
        if moves:
            st.emit("placement.updated", {"placements": moves})
        ctx["moves"] = {m["instance_id"]: m for m in moves}
        ctx["on_board"] = set(ctx["moves"])
        n_fp = sum(1 for pl in entry["placements"] if pl.get("on_pcb"))
        st.done(
            message=(
                f"{n_fp} footprints placed on a {entry['size_mm'][0]:.0f} x "
                f"{entry['size_mm'][1]:.0f} mm board outline"
            )[:200]
        )
        return board

    def _controller_check(
        self, run: BuildRun, st: _Stage, result: ComposeResult, board: dict[str, Any]
    ) -> None:
        slot = next((s for s in result.slots if s.slot_id == "controller"), None)
        used = {c for c in (board.get("controller") or {}).values() if c}
        if slot is None or slot.chosen is None or not used:
            return
        chosen = slot.chosen["part_id"].split(":")[-1]
        if not any(u in chosen or chosen in u for u in used):
            self._warn(
                run,
                "place",
                "w_mcu_board",
                "other",
                "info",
                f"The KiCad pin budget put {', '.join(sorted(used))} on the board; the "
                f"chosen part is {slot.chosen.get('display_name')}. "
                + "; ".join(board.get("log", [])[:2]),
            )

    def _moves(
        self,
        entry: dict[str, Any],
        side: str,
        origin: list[float],
        slots: dict[str, Slot],
        brief: dict[str, Any],
    ) -> list[dict[str, Any]]:
        t = float(entry.get("thickness_mm") or 1.6)
        out: list[dict[str, Any]] = []

        def mk(iid: str, pos: list[float], rot: list[float], mode: str, up: float) -> dict:
            pl: dict[str, Any] = {
                "mode": mode,
                "position_mm": [round(v, 3) for v in pos],
                "rotation_deg": [round(v, 3) for v in rot],
                "explode_offset_mm": [0.0, 0.0, up],
                "source": "solver",
                "locked": False,
            }
            if mode == "layout":
                pl["layout_id"] = {"left": "lay_l", "right": "lay_r"}.get(side, "lay_main")
            return {"instance_id": iid, "placement": pl}

        for sid, up in (("switches", 12.0), ("stabilizers", 6.0), ("keycaps", 25.0)):
            slot = slots.get(sid)
            if slot is None or slot.chosen is None:
                continue
            for inst in slot.instances:
                if inst.side != side and side != "none":
                    continue
                z = t
                if sid == "keycaps":
                    z = t + self._cap_seat(slots, brief)
                m = mk(inst.instance_id, [origin[0], origin[1], z], [0, 0, 0], "layout", up)
                if inst.key_widths is not None:
                    m["placement"]["key_widths_u"] = list(inst.key_widths)
                out.append(m)
        by_role: dict[str, list[dict[str, Any]]] = {}
        for p in entry["placements"]:
            by_role.setdefault(p["role"], []).append(p)
        for role, sid in ROLE_SLOT.items():
            slot = slots.get(sid)
            if slot is None or slot.chosen is None:
                continue
            insts = [i for i in slot.instances if i.side == side or side == "none"]
            for inst, p in zip(insts, by_role.get(role, []), strict=False):
                pos = list(p["placement"]["position_mm"])
                pos[2] = t + pos[2]
                out.append(
                    mk(inst.instance_id, pos, p["placement"]["rotation_deg"], "single", 15.0)
                )
                if sid == "encoder" and slots.get("knob") and slots["knob"].chosen is not None:
                    knob = [i for i in slots["knob"].instances if i.side == inst.side]
                    if knob:
                        kpos = [pos[0], pos[1], t + float(p.get("height_mm") or 20.0) - 6.0]
                        out.append(mk(knob[0].instance_id, kpos, [0, 0, 0], "single", 30.0))
        return out

    def _cap_seat(self, slots: dict[str, Slot], brief: dict[str, Any]) -> float:
        sw = slots.get("switches")
        bbox = ((sw.chosen or {}).get("mechanical") or {}).get("bbox_mm") if sw else None
        if bbox and bbox.get("max"):
            return float(bbox["max"][2])
        fam = "choc" if str(brief.get("switch_family", "")).startswith("choc") else "mx"
        return CAP_SEAT_MM[fam]

    # ---- enclose -------------------------------------------------------------------------
    async def enclose(
        self,
        run: BuildRun,
        brief: dict[str, Any],
        plan: KeyboardPlan | None,
        result: ComposeResult,
        board: dict[str, Any] | None,
        ctx: dict[str, Any],
    ) -> None:
        st = self._stage(run, "enclose", "Generating the case from the board outline")
        records = ctx.get("records") or []
        reports: dict[str, Any] = {}
        moves = ctx.get("moves") or {}
        parts_by_side: dict[str, list[dict[str, Any]]] = {}
        for p in run.state["parts"]:
            parts_by_side.setdefault(p.get("side") or "none", []).append(p)
        checks: list[dict[str, Any]] = []
        if not records:
            self._warn(run, "enclose", "w_case", "other", "warning", "No board outline, no case.")
            st.done("degraded", "No board outline to build a case around.")
            ctx["reports"] = reports
            return
        for i, record in enumerate(records):
            side = record.get("side") or "none"
            side = side if side in ("left", "right") else "none"
            mine = parts_by_side.get(side, []) + (
                parts_by_side.get("none", []) if side != "none" else []
            )
            st.progress(f"Case for the {side if side != 'none' else 'board'}", i / len(records))
            extra = [p for p in mine if p["instance_id"] not in ctx.get("on_board", set())]
            report, err = await asyncio.to_thread(A.run_enclose, record, extra, brief)
            ids = [p["instance_id"] for p in mine]
            if report is None:
                self._warn(run, "enclose", "w_case", "other", "warning", f"Case: {err}")
                st.emit("enclosure.updated",
                        {"enclosure": A.fallback_enclosure(record, brief, ids, side)})  # fmt: skip
                continue
            enclosure = copy.deepcopy(report.enclosure)
            enclosure["for_instance_ids"] = ids
            if side == "none":  # one-board build: GEOMETRY guesses a half from the centroid
                enclosure["side"], enclosure["enclosure_id"] = "none", "e_case"
            st.emit("enclosure.updated", {"enclosure": enclosure})
            reports[side] = report
            old_id = report.enclosure["enclosure_id"]
            for c in report.checks:
                c = json.loads(json.dumps(c).replace(old_id, enclosure["enclosure_id"]))
                c["stage"] = "enclose"
                checks.append(c)
            tented = []
            for iid in ids:
                m = moves.get(iid)
                if m is None:
                    continue
                pl = copy.deepcopy(m["placement"])
                pos, rot = report.place(pl["position_mm"], pl["rotation_deg"])
                pl["position_mm"] = [round(v, 3) for v in pos]
                pl["rotation_deg"] = [round(v, 3) for v in rot]
                tented.append({"instance_id": iid, "placement": pl})
            if tented and report.board_pose() != ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]):
                st.emit("placement.updated", {"placements": tented})
        if checks:
            st.emit("check.result", {"results": checks})
        ctx["reports"] = reports
        st.done()

    # ---- board ---------------------------------------------------------------------------
    async def board_stage(
        self, run: BuildRun, board: dict[str, Any] | None, result: ComposeResult, ctx: dict
    ) -> dict[str, Any] | None:
        st = self._stage(run, "board", "Routing and checking the KiCad boards")
        if board is None:
            if ctx.get("board_err"):
                st.done("failed", f"No KiCad board: {ctx['board_err']}")
            else:
                st.done("skipped", "No KiCad board for this build.")
            return None
        # The boards appear (outline and footprints, pending) before routing and the GLB
        # export, which take most of this stage; the routed records replace them.
        reports = ctx.get("reports") or {}
        planned_ids = self._instance_map(board, result)
        for entry in board["boards"]:
            preview = A.pending_board(entry)
            side = preview.get("side") or "none"
            self._map_board_ids(preview, planned_ids, run, side)
            report = reports.get(side) or reports.get("none")
            if report is not None:
                pos, rot = report.board_pose()
                preview["position_mm"] = [round(v, 3) for v in pos]
                preview["rotation_deg"] = [round(v, 3) for v in rot]
            st.emit("board.updated", {"board": preview})
        routed, err = await A.route_board(board, st.progress, effort=ctx.get("route_effort", 0))
        if routed is None:
            self._warn(run, "board", "w_board", "other", "warning", f"No KiCad board: {err}")
            st.emit(
                "check.result",
                {
                    "results": [
                        {
                            "check_key": "board.built:all",
                            "rule_id": "board.built",
                            "status": "fail",
                            "severity": "error",
                            "message": f"KiCad board not built: {err}"[:200],
                            "subjects": [],
                            "measured": None,
                            "limit": None,
                            "unit": None,
                            "stage": "board",
                        }
                    ]
                },
            )
            st.done("failed", f"No KiCad board: {err}")
            return None
        board = routed
        id_map = self._instance_map(board, result)
        results = []
        for entry in board["boards"]:
            spec_board = copy.deepcopy(entry["board"])
            side = spec_board.get("side") or "none"
            self._map_board_ids(spec_board, id_map, run, side)
            for net in spec_board.get("nets", []):
                for m in net.get("members", []):
                    m["instance_id"] = id_map.get(m["instance_id"], m["instance_id"])
                    m.setdefault("index", None)
            report = reports.get(side) or reports.get("none")
            if report is not None:
                pos, rot = report.board_pose()
                spec_board["position_mm"] = [round(v, 3) for v in pos]
                spec_board["rotation_deg"] = [round(v, 3) for v in rot]
            evaluation = evaluate_board(
                spec_board["board_id"],
                spec_board.get("nets", []),
                entry.get("drc") or {},
                entry.get("routing") or {},
                entry.get("timings") or {},
            )
            spec_board["evaluation"] = evaluation["summary"]
            spec_board["revision"] = 1
            st.emit("board.updated", {"board": spec_board})
            seated = _seat_on_footprints(spec_board, run.state["parts"])
            if seated:
                st.emit("placement.updated", {"placements": seated})
            drc = entry.get("drc") or {}
            bid = spec_board["board_id"]
            errors, unconnected = int(drc.get("errors", 0)), int(drc.get("unconnected", 0))
            results.append(
                {
                    "check_key": f"board.drc:{bid}",
                    "rule_id": "board.drc",
                    "status": "pass" if errors == 0 else "fail",
                    "severity": "error",
                    "message": f"PCB: {errors} errors, {unconnected} unconnected (kicad-cli DRC)",
                    "subjects": [{"board_id": bid}],
                    "measured": errors,
                    "limit": 0,
                    "unit": "count",
                    "stage": "board",
                }
            )
            results.append(
                {
                    "check_key": f"board.routing.complete:{bid}",
                    "rule_id": "board.routing.complete",
                    "status": "pass" if unconnected == 0 else "fail",
                    "severity": "error",
                    "message": (
                        f"Autorouted with {spec_board['routing'].get('router')}: "
                        f"{unconnected} unconnected"
                        + (" (cached)" if entry.get("cache_hit") else "")
                    ),
                    "subjects": [{"board_id": bid}],
                    "measured": unconnected,
                    "limit": 0,
                    "unit": "count",
                    "stage": "board",
                }
            )
            results.extend(evaluation["checks"])
        st.emit("check.result", {"results": results})
        failed = any(r["status"] == "fail" for r in results)
        t = board.get("timings") or {}
        st.done(
            "ok" if not failed else "degraded",
            ("DRC or routing left issues; " if failed else "")
            + f"pcbnew + Freerouting + DRC + GLB {t.get('route_total_s', 0):.1f} s"
            + (" (cached)" if all(e.get("cache_hit") for e in board["boards"]) else ""),
        )
        return board

    @staticmethod
    def _map_board_ids(
        spec_board: dict[str, Any], id_map: dict[str, str], run: BuildRun, side: str
    ) -> None:
        """Board-local instance ids -> the build's, on for_instance_ids and footprints.
        A footprint with no build part (diodes, sockets) keeps instance_id null."""
        live = {p["instance_id"] for p in run.state["parts"]}
        spec_board["for_instance_ids"] = [
            p["instance_id"] for p in run.state["parts"] if p.get("side") in (side, "none")
        ]
        for fp in spec_board.get("footprints") or []:
            mapped = id_map.get(fp.get("instance_id") or "")
            fp["instance_id"] = mapped if mapped in live else None

    def _instance_map(self, board: dict[str, Any], result: ComposeResult) -> dict[str, str]:
        out: dict[str, str] = {}
        slots = {s.slot_id: s for s in result.slots}
        for entry in board["boards"]:
            side = entry.get("side") or "none"
            by_role: dict[str, list[str]] = {}
            for p in entry["placements"]:
                if p.get("for_instance_id"):
                    out[p["instance_id"]] = p["for_instance_id"]
                    continue
                by_role.setdefault(p["role"], []).append(p["instance_id"])
            for role, sid in {**ROLE_SLOT, "switch": "switches"}.items():
                slot = slots.get(sid)
                if slot is None or slot.chosen is None:
                    continue
                insts = [i.instance_id for i in slot.instances if i.side in (side, "none")]
                if not insts:
                    continue
                for n, bid in enumerate(by_role.get(role, [])):
                    out[bid] = insts[min(n, len(insts) - 1)]
        return out

    # ---- firmware ------------------------------------------------------------------------
    def firmware(
        self,
        run: BuildRun,
        brief: dict[str, Any],
        plan: KeyboardPlan | None,
        result: ComposeResult,
        board: dict[str, Any] | None,
    ) -> None:
        st = self._stage(run, "firmware", "Writing firmware")
        firmware, checks = make_firmware(brief, plan, result.slots, board)
        if not firmware["targets"]:
            st.done("skipped", "No controller in the build, so no firmware.")
            return
        st.emit("firmware.ready", {"firmware": firmware})
        if checks:
            st.emit("check.result", {"results": checks})
        st.done()

    # ---- render --------------------------------------------------------------------------
    def render(
        self, run: BuildRun, result: ComposeResult, board: dict[str, Any] | None, ctx: dict
    ) -> None:
        st = self._stage(run, "render", "Preparing the 3D scene")
        preload: list[str] = []

        def add(url: str | None) -> None:
            if url and url not in preload:
                preload.append(url)

        for enc in run.state["enclosures"]:
            for a in enc.get("assets", []):
                if a.get("kind") == "glb":
                    add(a.get("url"))
        for b in run.state["boards"]:
            for a in b.get("assets", []):
                if a.get("kind") == "glb":
                    add(a.get("url"))
        for part in result.chosen_parts.values():
            asset = model_asset(part)
            add(asset.get("url") if asset else None)
        lo, hi = [1e9, 1e9, 1e9], [-1e9, -1e9, -1e9]
        for enc in run.state["enclosures"]:
            pos, size = enc.get("position_mm") or [0, 0, 0], enc.get("outer_size_mm") or [0, 0, 0]
            for k in range(3):
                lo[k] = min(lo[k], pos[k] - size[k] / 2 if k < 2 else pos[k])
                hi[k] = max(hi[k], pos[k] + size[k] / 2 if k < 2 else pos[k] + size[k])
        for b in run.state["boards"]:
            for x, y in b.get("outline_mm") or []:
                lo[0], lo[1] = min(lo[0], x), min(lo[1], y)
                hi[0], hi[1] = max(hi[0], x), max(hi[1], y)
        if lo[0] > hi[0]:
            lo, hi = [-60.0, -40.0, 0.0], [60.0, 40.0, 30.0]
        lo[2], hi[2] = min(lo[2], 0.0), max(hi[2], lo[2] + 10.0)
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        span = max(hi[0] - lo[0], hi[1] - lo[1], 60.0)
        scene = {
            "camera": {
                "position_mm": [round(cx, 1), round(cy - span * 0.95, 1), round(span * 0.8, 1)],
                "target_mm": [round(cx, 1), round(cy, 1), round((lo[2] + hi[2]) / 2, 1)],
                "fov_deg": 35,
            },
            "assembly_bbox_mm": {
                "min": [round(v, 2) for v in lo],
                "max": [round(v, 2) for v in hi],
            },
            "render": None,
            "preload": preload,
        }
        st.emit("scene.ready", {"scene": scene})
        st.emit("check.result", {"results": [self._models_check(run)]})
        st.done()

    @staticmethod
    def _models_check(run: BuildRun) -> dict[str, Any]:
        """Parts the viewer can only draw as a box: no model, or a model URL with no file."""

        def served(url: str) -> bool:
            if not url.startswith("/assets/") or "/kicad_gen/" in url:
                return True  # remote, or converted on first request
            return (ASSETS_DIR / url.removeprefix("/assets/")).is_file()

        boxes: list[str] = []
        for p in run.state["parts"]:
            card = p.get("card") or {}
            if card.get("kind") == "fastener":
                continue  # a mounting hole is a hole in the board, drawn by the board
            a = model_asset({"assets": p.get("assets") or card.get("assets") or []})
            name = str(card.get("display_name") or p.get("part_id"))
            if (
                a is None or a.get("status") == "missing" or not served(str(a.get("url") or ""))
            ) and name not in boxes:
                boxes.append(name)
        return {
            "check_key": "render.models",
            "rule_id": "render.models",
            "status": "fail" if boxes else "pass",
            "severity": "warning",
            "message": (
                f"No 3D model, drawn as a box: {', '.join(boxes)}"
                if boxes
                else "Every part has a 3D model"
            )[:300],
            "subjects": [],
            "stage": "render",
        }


def make_runner(engine: Engine, source: PartSource) -> LiveRunner:
    return LiveRunner(engine, source)


def is_live(settings: Any, options: dict[str, Any]) -> bool:
    return not settings.mock and not options.get("mock_fixture")
