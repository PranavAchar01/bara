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

from bara.live import adapters as A
from bara.live.brief import BriefResult, spec_from_brief, write_brief
from bara.live.catalog_source import PartSource, merge_into_catalog, model_asset
from bara.live.compose import Composer, ComposeResult, Slot
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


class LiveRunner:
    def __init__(self, engine: Engine, source: PartSource) -> None:
        self.engine = engine
        self.source = source
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
        merge_into_catalog(self.catalog, list(result.chosen_parts.values()))
        board = await self.place(run, brief, plan, result, ctx)
        await self.enclose(run, brief, plan, result, board, ctx)
        self.board_stage(run, board, result, ctx)
        self.firmware(run, brief, plan, result, board)
        self.render(run, result, board, ctx)
        run.emit("build.done", self.engine._done_payload(run, {}))

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
        top = considered[:3]
        reason = "Generating a new KiCad board, case and firmware from the brief."
        if top:
            reason += f" Closest open design: {top[0]['name']}, compared only, not copied."
        st.emit(
            "reuse.decided",
            {
                "tier": "compose",
                "design_id": None,
                "design": None,
                "considered": top,
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
        composer = Composer(self.source, spec, brief, plan, self.settings, controllers)
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
            return await self._place_generic(run, result, ctx)

        st = self._stage(run, "place", "Placing parts on a KiCad board")
        ctrl = slots.get("controller")
        mcu_label = (ctrl.chosen or {}).get("display_name") if ctrl else None
        bb = A.board_brief(brief, mcu_label)
        board, err = await A.run_board(bb, result.parts, run.build_id, st.progress)
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
                {"x": p["x_mm"], "y": p["y_mm"], "rot": p["rot_deg"], "matrix": p.get("matrix")}
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

    async def _place_generic(
        self, run: BuildRun, result: ComposeResult, ctx: dict[str, Any]
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
        board, err = await A.run_board({"generic": True}, parts, run.build_id, st.progress)
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
        drc = entry.get("drc") or {}
        n_fp = sum(1 for pl in entry["placements"] if pl.get("on_pcb"))
        st.done(
            message=(
                f"{n_fp} footprints on a {entry['board']['size_mm'][0]:.0f} x "
                f"{entry['board']['size_mm'][1]:.0f} mm board; DRC {drc.get('errors', '?')} "
                f"errors, {drc.get('unconnected', '?')} unconnected"
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

        for sid, up in (("switches", 12.0), ("keycaps", 25.0)):
            slot = slots.get(sid)
            if slot is None or slot.chosen is None:
                continue
            for inst in slot.instances:
                if inst.side != side and side != "none":
                    continue
                z = t
                if sid == "keycaps":
                    z = t + self._cap_seat(slots, brief)
                out.append(mk(inst.instance_id, [origin[0], origin[1], z], [0, 0, 0], "layout", up))
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
    def board_stage(
        self, run: BuildRun, board: dict[str, Any] | None, result: ComposeResult, ctx: dict
    ) -> None:
        st = self._stage(run, "board", "Routing and checking the KiCad boards")
        if board is None:
            if ctx.get("board_err"):
                st.done("failed", f"No KiCad board: {ctx['board_err']}")
            else:
                st.done("skipped", "No KiCad board for this build.")
            return
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
        st.done(
            "ok" if not failed else "degraded", "DRC or routing left issues" if failed else None
        )

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
