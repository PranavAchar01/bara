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
import time
from typing import TYPE_CHECKING, Any

from shapely.geometry import Polygon

from bara.live import adapters as A
from bara.live import archetype, completeness, hero
from bara.live import blocks as blocks_mod
from bara.live import form as form_mod
from bara.live import identity as identity_mod
from bara.live.brief import BriefResult, normalise_brief, spec_from_brief, write_brief
from bara.live.catalog_source import PartSource, merge_into_catalog, model_asset
from bara.live.compose import Composer, ComposeResult, Slot
from bara.live.fetch import as_overlay
from bara.live.firmware import make_firmware
from bara.live.layout import KeyboardPlan, plan_keyboard
from bara.util import error_obj

if TYPE_CHECKING:
    from bara.engine import BuildRun, Engine

log = logging.getLogger(__name__)

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


def _spans(product: form_mod.Form, size: tuple[float, float]) -> bool:
    """True when the form already has the declared width and height (either way round)."""
    xs = [p[0] for p in product.silhouette]
    ys = [p[1] for p in product.silhouette]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    return any(abs(a - b) <= 0.1 * b for a, b in ((w, size[0]), (h, size[1]))) and any(
        abs(a - b) <= 0.1 * b for a, b in ((w, size[1]), (h, size[0]))
    )


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
        return _Stage(run, self.catalog.stage_budget(stage), stage, label)

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
        plan = plan_keyboard(brief)
        self.reuse(run, spec, brief)
        result = await self.compose(run, spec, brief, plan)
        if not result.chosen_parts:  # nothing resolved is a failed build, never an empty DONE
            why = "No part could be chosen for this request; nothing to build."
            run.emit("build.failed", {"error": error_obj("E_NO_PARTS", why, stage="compose")})
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
        failure = self.gate(run)
        if failure is not None:
            run.emit("build.failed", {"error": failure})
            return
        run.emit("build.done", self.engine._done_payload(run, {}))

    # checks that decide whether the product exists: any one failing ends the build as failed
    FIT_REPAIRS = 2
    REQUIRED = {
        "device.complete": "E_CRITICAL_PART_MISSING",
        "slot.critical_filled": "E_CRITICAL_PART_MISSING",
        "form.valid": "E_ENCLOSURE_FAILED",
        "form.fit": "E_ENCLOSURE_FAILED",
        "identity.reads_as_device": "E_ENCLOSURE_FAILED",
        "board.drc": "E_BOARD_FAILED",
        "board.routing.complete": "E_BOARD_FAILED",
        "mech.fit.enclosure": "E_ENCLOSURE_FAILED",
        "mech.fit.collision": "E_ENCLOSURE_FAILED",
        "mech.fit.floating": "E_ENCLOSURE_FAILED",
    }

    def gate(self, run: BuildRun) -> dict[str, Any] | None:
        """A failing required check is a failed build, never a clean DONE. The artefacts stay
        in the build state so the failure can be looked at."""
        latest: dict[str, dict[str, Any]] = {}
        for check in run.state["checks"]:
            latest[check.get("rule_id") or check.get("check_key") or ""] = check
        bad = [
            (rid, latest[rid])
            for rid in self.REQUIRED
            if latest.get(rid, {}).get("status") == "fail"
        ]
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
    def reuse(self, run: BuildRun, spec: dict[str, Any], brief: dict[str, Any]) -> None:
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
            if considered:
                reason += f" Closest open design: {considered[0]['name']}, compared only."
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
            blocks, note = await blocks_mod.derive(run.prompt, self.catalog.function_ids())
            if blocks is None:
                msg = f"No function block diagram ({note}); only the general invariants apply."
                self._warn(run, "compose", "w_blocks", "other", "warning", msg)
        run.live_blocks = blocks  # type: ignore[attr-defined]
        composer = Composer(
            self.source, spec, brief, plan, self.settings, controllers, blocks=blocks
        )
        st.emit("slots.ready", {"slots": [s.json() for s in composer.slots]})
        if plan is not None:
            for half in plan.halves:
                lid = {"left": "lay_l", "right": "lay_r"}.get(half.side, "lay_main")
                name = f"{plan.key_count} key {plan.style}" + (
                    f" {half.side}" if half.side != "none" else ""
                )
                st.emit("layout.added", {"layout": plan.layout_json(half, lid, name)})
        result = await composer.run(st.emit, st.progress)
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
                    form_mod.Touch(slot.slot_id, slot.label, fid, max(1, slot.quantity), groups)
                )
        return out

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
        product, note = await form_mod.derive(
            run.prompt, touches, previous if (repair or fit) else None, repair, fit
        )
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
        if product is not None and meshes:
            eye, target = hero.hero_camera(meshes)
            png = await asyncio.to_thread(hero.render, meshes, eye, target)
            out = root / "cache" / "hero"
            out.mkdir(parents=True, exist_ok=True)
            run.hero_png = out / f"{run.build_id}{'_repaired' if final else ''}.png"  # type: ignore[attr-defined]
            run.hero_png.write_bytes(png)  # type: ignore[attr-defined]
            verdict, note = await identity_mod.judge(
                run.prompt, product.description, product.reference, png
            )
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
        st.emit(
            "check.result",
            {
                "results": [
                    {
                        "check_key": "identity.reads_as_device",
                        "rule_id": "identity.reads_as_device",
                        "status": "pass" if ok else ("fail" if verdict else "unknown"),
                        "severity": "error",
                        "message": message[:300],
                        "subjects": [],
                        "stage": "render",
                    }
                ]
            },
        )
        st.done()
        if verdict is not None and not ok and not final:
            return identity_mod.critique(verdict)
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
        top = bottom = 0.0
        thick = 1.6
        for entry in board["boards"]:
            thick = float(entry.get("thickness_mm") or thick)
            for pl in entry["placements"]:
                h = float(pl.get("height_mm") or 0.0)
                if pl.get("side") == "bottom":
                    bottom = max(bottom, h)
                else:
                    top = max(top, h)
        stack = top + thick + bottom + 2 * self.WALL_STACK_MM + self.STACK_CLEARANCE_MM
        if stack > product.thickness_mm:
            self._warn(
                run, "place", "w_stack", "other", "info",
                f"Body thickened {product.thickness_mm:.0f} -> {stack:.0f} mm: the parts stack "
                f"{top:.1f} mm above and {bottom:.1f} mm below the board.",
            )  # fmt: skip
            brief["body_thickness_mm"] = stack

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
        board, err = await asyncio.to_thread(A.plan_board, gb, parts, run.build_id)
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
        routed, err = await A.route_board(board, st.progress)
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
        reports = ctx.get("reports") or {}
        id_map = self._instance_map(board, result)
        results = []
        for entry in board["boards"]:
            spec_board = copy.deepcopy(entry["board"])
            side = spec_board.get("side") or "none"
            mine = [p["instance_id"] for p in run.state["parts"] if p.get("side") in (side, "none")]
            spec_board["for_instance_ids"] = mine
            for net in spec_board.get("nets", []):
                for m in net.get("members", []):
                    m["instance_id"] = id_map.get(m["instance_id"], m["instance_id"])
                    m.setdefault("index", None)
            report = reports.get(side) or reports.get("none")
            if report is not None:
                pos, rot = report.board_pose()
                spec_board["position_mm"] = [round(v, 3) for v in pos]
                spec_board["rotation_deg"] = [round(v, 3) for v in rot]
            spec_board["revision"] = 1
            st.emit("board.updated", {"board": spec_board})
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
        st.done()


def make_runner(engine: Engine, source: PartSource) -> LiveRunner:
    return LiveRunner(engine, source)


def is_live(settings: Any, options: dict[str, Any]) -> bool:
    return not settings.mock and not options.get("mock_fixture")
