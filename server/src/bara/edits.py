"""Live edit engine (SPEC.md 8.4 and 8.7).

plan() validates a whole edit against a copy of the reduced build and returns either the
ordered list of model change events (accepted) or a rejection (error, failed_checks,
suggestions). The engine (engine.py) stamps seq, revision and cause and emits them.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bara.catalog import Catalog
from bara.reducer import apply_event
from bara.schemas import SchemaSet
from bara.util import error_obj

SIDES = {"left", "right", "center"}


class Reject(Exception):
    def __init__(
        self,
        error: dict[str, Any],
        failed_checks: list[dict[str, Any]] | None = None,
        suggestions: list[dict[str, Any]] | None = None,
        stage_message: str | None = None,
    ) -> None:
        super().__init__(error["message"])
        self.error = error
        self.failed_checks = failed_checks or []
        self.suggestions = suggestions or []
        self.stage_message = stage_message or error["message"]


@dataclass
class EditPlan:
    label: str
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    rejection: Reject | None = None


def _bad(code: str, message: str, **kw: Any) -> Reject:
    return Reject(error_obj(code, message, stage="edit", **kw))


def phrase(label: str) -> tuple[str, str | None]:
    """'OLED left' -> ('OLED', 'left')."""
    words = label.split()
    if len(words) > 1 and words[-1].lower() in SIDES:
        return " ".join(words[:-1]), words[-1].lower()
    return label, None


def lower_first(text: str) -> str:
    first = text.split()[0] if text else ""
    return text if first.isupper() else text[:1].lower() + text[1:]


def owner_phrase(label: str) -> str:
    base, side = phrase(label)
    return f"{side} {base}" if side else base


class EditEngine:
    def __init__(self, catalog: Catalog, rules_path: Path, schemas: SchemaSet) -> None:
        self.catalog = catalog
        self.schemas = schemas
        data = json.loads(rules_path.read_text()) if rules_path.exists() else {}
        self.rules: list[dict[str, Any]] = data.get("connection_rules", [])
        self.slot_rule: dict[str, Any] = data.get("slot_rule", {})
        self.delta_labels: dict[str, str] = data.get("delta_labels", {})

    # ---- lookups on a working build -------------------------------------
    @staticmethod
    def _inst(work: dict[str, Any], instance_id: str) -> dict[str, Any] | None:
        return next((p for p in work["parts"] if p["instance_id"] == instance_id), None)

    def _iface(self, work: dict[str, Any], end: dict[str, Any]) -> dict[str, Any] | None:
        inst = self._inst(work, end["instance_id"])
        return self.catalog.interface(inst["part_id"], end["interface_id"]) if inst else None

    @staticmethod
    def _slot(work: dict[str, Any], slot_id: str | None) -> dict[str, Any] | None:
        return next((s for s in work["slots"] if s["slot_id"] == slot_id), None)

    def _design_name(self, work: dict[str, Any]) -> str:
        design = self.catalog.designs.get(work.get("design_id") or "")
        if not design:
            return "build"
        return re.sub(r"\s*\([^)]*\)", "", design["name"]).strip()

    def _fill(self, template: str, values: dict[str, Any]) -> str:
        out = template
        for key, value in values.items():
            out = out.replace("{" + key + "}", str(value))
        return out

    # ---- connection rules ----------------------------------------------
    def evaluate(self, work: dict[str, Any], conn: dict[str, Any]) -> list[dict[str, Any]]:
        """One entry per applicable rule: {rule, status, measured, limit, values, key}."""
        out = []
        for rule in self.rules:
            if rule["connection_type"] != conn["type"]:
                continue
            req = self._iface(work, conn["to"])
            prov = self._iface(work, conn["from"])
            if not req or not prov:
                continue
            measured = req.get("params", {}).get(rule["param"])
            limit = prov.get("params", {}).get(rule["param"])
            if measured is None or limit is None:
                continue
            m_label = self.catalog.facet_label(rule["facet"], measured)
            l_label = self.catalog.facet_label(rule["facet"], limit)
            taxonomy = (work.get("spec") or {}).get("taxonomy_path") or []
            values = {
                "measured": m_label,
                "limit": l_label,
                "measured_word": m_label.split()[0] if m_label else m_label,
                "design": self._design_name(work),
                "kind": taxonomy[1].replace("_", " ") if len(taxonomy) > 1 else "device",
                "form": taxonomy[2].replace("_", " ") if len(taxonomy) > 2 else "",
            }
            out.append(
                {
                    "rule": rule,
                    "status": "pass" if measured == limit else "fail",
                    "measured": measured,
                    "limit": limit,
                    "values": values,
                    "requirer": conn["to"]["instance_id"],
                    "provider": conn["from"]["instance_id"],
                    "key": f"{rule['rule_id']}:{conn['to']['instance_id']}",
                }
            )
        return out

    def _pass_result(self, ev: dict[str, Any]) -> dict[str, Any]:
        rule = ev["rule"]
        return {
            "check_key": ev["key"],
            "rule_id": rule["rule_id"],
            "status": "pass",
            "severity": self.catalog.check_severity(rule["rule_id"]),
            "message": self._fill(rule["pass"], ev["values"])[:300],
            "subjects": [{"instance_id": ev["requirer"]}],
            "stage": "edit",
        }

    def _fail_result(self, ev: dict[str, Any], short: bool) -> dict[str, Any]:
        rule = ev["rule"]
        result: dict[str, Any] = {
            "check_key": ev["key"],
            "rule_id": rule["rule_id"],
            "status": "fail",
            "severity": self.catalog.check_severity(rule["rule_id"]),
            "message": self._fill(rule["fail_short" if short else "fail_long"], ev["values"])[:300],
        }
        if short:
            result["subjects"] = [{"instance_id": ev["requirer"]}]
            return result
        result["subjects"] = [{"instance_id": ev["requirer"]}, {"instance_id": ev["provider"]}]
        result["measured"] = ev["measured"]
        result["limit"] = ev["limit"]
        result["fix_hint"] = self._fill(rule.get("fix_hint", ""), ev["values"])[:200] or None
        result["stage"] = "edit"
        return result

    def connections_of(self, work: dict[str, Any], instance_id: str) -> list[dict[str, Any]]:
        return [
            c
            for c in work["connections"]
            if instance_id in (c["from"]["instance_id"], c["to"]["instance_id"])
        ]

    # ---- swap drawer -------------------------------------------------------
    @staticmethod
    def _spec_text(spec: dict[str, Any]) -> str:
        unit = spec.get("unit")
        return f"{spec['value']} {unit}" if unit else str(spec["value"])

    def deltas(self, current: dict[str, Any] | None, new: dict[str, Any]) -> list[dict[str, Any]]:
        if not current:
            return []
        old = {s["label"]: s for s in current.get("key_specs", [])}
        out = []
        for spec in new.get("key_specs", []):
            before = old.get(spec["label"])
            if before is None or before.get("value") == spec.get("value"):
                continue
            label = self.delta_labels.get(spec["label"], spec["label"])
            out.append(
                {"label": label, "from": self._spec_text(before), "to": self._spec_text(spec)}
            )
        return out[:4]

    def alternatives(
        self, build: dict[str, Any], slot_id: str, instance_id: str | None, limit: int
    ) -> dict[str, Any]:
        """Swap drawer items for one slot, each checked by simulating the swap."""
        slot = self._slot(build, slot_id)
        if slot is None:
            raise _bad("E_NOT_FOUND", f"No slot {slot_id} in this build.")
        inst = self._inst(build, instance_id) if instance_id else None
        if instance_id and (inst is None or inst.get("slot_id") != slot_id):
            raise _bad(
                "E_UNKNOWN_INSTANCE",
                f"No part {instance_id} in slot {slot_id}.",
                subjects=[{"instance_id": instance_id}],
            )
        if inst is None:
            inst = next((p for p in build["parts"] if p.get("slot_id") == slot_id), None)
        current_id = inst["part_id"] if inst else None
        function = (
            self.catalog.primary_function(current_id) if current_id else slot.get("function_id")
        )
        items = []
        for part_id, card in self.catalog.cards.items():
            if part_id == current_id or self.catalog.primary_function(part_id) != function:
                continue
            item: dict[str, Any] = {"card": copy.deepcopy(card), "compatible": True}
            failed: list[dict[str, Any]] = []
            if inst is not None:
                try:
                    _, _, evals = self.simulate_swap(build, inst["instance_id"], part_id)
                    failed = [
                        self._fail_result(e, short=True) for e in evals if e["status"] == "fail"
                    ]
                except Reject:
                    item["compatible"] = False
            item["compatible"] = item["compatible"] and not failed
            item["failed_checks"] = failed
            item["deltas"] = self.deltas(inst["card"] if inst else None, card)
            items.append(item)
            if len(items) >= limit:
                break
        return {
            "slot_id": slot_id,
            "instance_id": inst["instance_id"] if inst else None,
            "current_part_id": current_id,
            "items": items,
        }

    # ---- swap ------------------------------------------------------------
    def simulate_swap(
        self, work: dict[str, Any], instance_id: str, part_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Returns (new BuildPart, re-resolved connections, rule evaluations).

        Raises Reject on unknown ids or a missing interface.
        """
        inst = self._inst(work, instance_id)
        if inst is None:
            raise _bad(
                "E_UNKNOWN_INSTANCE",
                f"No part {instance_id} in this build.",
                subjects=[{"instance_id": instance_id}],
            )
        card = self.catalog.card(part_id)
        if card is None or self.catalog.part(part_id) is None:
            raise _bad(
                "E_UNKNOWN_PART",
                f"No part {part_id} in the catalog.",
                subjects=[{"part_id": part_id}],
            )
        new_ifaces = self.catalog.interfaces(part_id)
        trial = copy.deepcopy(work)
        new_part = copy.deepcopy(inst)
        new_part["part_id"] = part_id
        new_part["card"] = copy.deepcopy(card)
        new_part["assets"] = copy.deepcopy(self.catalog.part(part_id).get("assets", []))
        new_part["origin"] = "user"
        new_part["status"] = "ok"
        apply_event(trial, {"type": "part.updated", "payload": {"part": new_part}})
        changed: list[dict[str, Any]] = []
        for conn in self.connections_of(work, instance_id):
            conn2 = copy.deepcopy(conn)
            for end_key, role in (("from", "provides"), ("to", "requires")):
                end = conn2[end_key]
                if end["instance_id"] != instance_id:
                    continue
                old = self.catalog.interface(inst["part_id"], end["interface_id"]) or {}
                want_role = old.get("role", role)
                matches = [
                    i
                    for i in new_ifaces
                    if i.get("type") == conn["type"] and i.get("role") == want_role
                ]
                if not matches:
                    raise Reject(
                        error_obj(
                            "E_INCOMPATIBLE",
                            f"{card['display_name']} has no {conn['type']} interface for "
                            f"{conn.get('label') or conn['connection_id']}.",
                            stage="edit",
                            subjects=[{"instance_id": instance_id}, {"part_id": part_id}],
                            details={"connection_id": conn["connection_id"]},
                        )
                    )
                same = next((i for i in matches if i.get("id") == end["interface_id"]), None)
                chosen = same or matches[0]
                if chosen["id"] != end["interface_id"]:
                    end["interface_id"] = chosen["id"]
            if conn2 != conn:
                changed.append(conn2)
                apply_event(trial, {"type": "connection.added", "payload": {"connection": conn2}})
        evals: list[dict[str, Any]] = []
        for conn in self.connections_of(trial, instance_id):
            evals += self.evaluate(trial, conn)
        return new_part, changed, evals

    def _swap_suggestions(
        self,
        work: dict[str, Any],
        instance_id: str,
        bad_part: str,
        ev: dict[str, Any],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        inst = self._inst(work, instance_id)
        function = self.catalog.primary_function(bad_part)
        for part_id in self.catalog.cards:
            if part_id in (bad_part, inst["part_id"] if inst else None):
                continue
            if self.catalog.primary_function(part_id) != function:
                continue
            try:
                _, _, evals = self.simulate_swap(work, instance_id, part_id)
            except Reject:
                continue
            if all(e["status"] == "pass" for e in evals):
                name = self.catalog.card(part_id)["display_name"]
                out.append(
                    {
                        "suggestion_id": "sg1",
                        "kind": "edit",
                        "label": f"Use {name} instead"[:80],
                        "prompt": None,
                        "ops": [
                            {"op": "swap_part", "instance_id": instance_id, "part_id": part_id}
                        ],
                        "design_id": None,
                    }
                )
                break
        rule = ev["rule"]
        if rule.get("suggest_label") and rule.get("suggest_prompt"):
            label = re.sub(r"\s+", " ", self._fill(rule["suggest_label"], ev["values"])).strip()
            prompt = re.sub(r"\s+", " ", self._fill(rule["suggest_prompt"], ev["values"])).strip()
            out.append(
                {
                    "suggestion_id": f"sg{len(out) + 1}",
                    "kind": "prompt",
                    "label": label[:80],
                    "prompt": prompt,
                    "ops": None,
                    "design_id": None,
                }
            )
        return out[:4]

    def _op_swap(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        instance_id, part_id = op["instance_id"], op["part_id"]
        new_part, changed, evals = self.simulate_swap(work, instance_id, part_id)
        failing = [e for e in evals if e["status"] == "fail"]
        if failing:
            ev = failing[0]
            other = self._inst(
                work, ev["provider"] if ev["requirer"] == instance_id else ev["requirer"]
            )
            values = dict(ev["values"])
            values["part"] = self.catalog.card(part_id)["display_name"]
            values["owner"] = (
                owner_phrase(other["label"]) if other and other.get("label") else "part"
            )
            raise Reject(
                error_obj(
                    "E_INCOMPATIBLE",
                    self._fill(ev["rule"]["error"], values),
                    stage="edit",
                    subjects=[{"instance_id": instance_id}, {"part_id": part_id}],
                    details={"rule_id": ev["rule"]["rule_id"]},
                ),
                failed_checks=[self._fail_result(ev, short=False)],
                suggestions=self._swap_suggestions(work, instance_id, part_id, ev),
                stage_message=self._fill(ev["rule"]["fail_short"], ev["values"]),
            )
        self._push(work, plan, "part.updated", {"part": new_part})
        for conn in changed:
            self._push(work, plan, "connection.added", {"connection": conn})
        tracked = {c["check_key"] for c in work["checks"]}
        for ev in evals:
            if ev["requirer"] != instance_id and ev["provider"] != instance_id:
                continue
            report = ev["rule"].get("report", "if_tracked")
            if report == "always" and ev["requirer"] == instance_id or ev["key"] in tracked:
                state["checks"].append(self._pass_result(ev))

    # ---- other ops -------------------------------------------------------
    def _op_remove(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        instance_id = op["instance_id"]
        inst = self._inst(work, instance_id)
        if inst is None:
            raise _bad(
                "E_UNKNOWN_INSTANCE",
                f"No part {instance_id} in this build.",
                subjects=[{"instance_id": instance_id}],
            )
        slot = self._slot(work, inst.get("slot_id"))
        if slot and slot.get("criticality") == "critical":
            others = [p for p in work["parts"] if p.get("slot_id") == slot["slot_id"]]
            if len(others) <= 1:
                values = {"part": inst["card"]["display_name"], "slot": slot["label"]}
                message = self._fill(
                    self.slot_rule.get("error", "Critical slot left empty."), values
                )
                check = {
                    "check_key": f"{self.slot_rule.get('rule_id', 'slot.critical_filled')}:build",
                    "rule_id": self.slot_rule.get("rule_id", "slot.critical_filled"),
                    "status": "fail",
                    "severity": "critical",
                    "message": message[:300],
                    "subjects": [{"slot_id": slot["slot_id"]}, {"instance_id": instance_id}],
                    "fix_hint": self.slot_rule.get("fix_hint"),
                    "stage": "edit",
                }
                raise Reject(
                    error_obj(
                        "E_CRITICAL_PART_MISSING",
                        message,
                        stage="edit",
                        subjects=[{"instance_id": instance_id}, {"slot_id": slot["slot_id"]}],
                        details={"slot_id": slot["slot_id"]},
                    ),
                    failed_checks=[check],
                )
        for conn in list(work["connections"]):
            ends = (
                conn["from"]["instance_id"],
                conn["to"]["instance_id"],
                conn.get("via_instance_id"),
            )
            if instance_id in ends:
                payload = {"connection_id": conn["connection_id"], "reason": "Part removed"}
                self._push(work, plan, "connection.removed", payload)
        payload = {"instance_id": instance_id, "reason": "Removed by user"}
        self._push(work, plan, "part.removed", payload)

    def _op_recolor(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        color = copy.deepcopy(op["color"])
        if op.get("instance_id"):
            inst = self._inst(work, op["instance_id"])
            if inst is None:
                raise _bad("E_UNKNOWN_INSTANCE", f"No part {op['instance_id']} in this build.")
            part = copy.deepcopy(inst)
            part["color"] = color
            self._push(work, plan, "part.updated", {"part": part})
            return
        enc = next(
            (e for e in work["enclosures"] if e["enclosure_id"] == op.get("enclosure_id")), None
        )
        if enc is None:
            raise _bad("E_INVALID_EDIT", f"No enclosure {op.get('enclosure_id')} in this build.")
        enc = copy.deepcopy(enc)
        enc["color"] = color
        enc["color_source"] = "user"
        enc["revision"] = int(enc.get("revision", 0)) + 1
        self._push(work, plan, "enclosure.updated", {"enclosure": enc})

    def _op_palette(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        """Change the shell palette (body, trim, buttons, accent, screen) and redo the finish."""
        from bara.live import finish as finish_mod

        have = ((work.get("scene") or {}).get("finish") or {}).get("palette") or {}
        merged = {k: have[k] for k in finish_mod.SHELL_KEYS if k in have}
        merged.update({k: v for k, v in op["palette"].items() if k in finish_mod.SHELL_KEYS})
        for msg_type, payload in finish_mod.events(work, None, merged):
            self._push(work, plan, msg_type, payload)

    def _op_move(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        inst = self._inst(work, op["instance_id"])
        if inst is None:
            raise _bad("E_UNKNOWN_INSTANCE", f"No part {op['instance_id']} in this build.")
        if op.get("index") is not None:
            raise _bad("E_INVALID_EDIT", "Moving one element of an arrayed part is not supported.")
        if "position_mm" not in op and "rotation_deg" not in op:
            raise _bad("E_INVALID_EDIT", "A move needs position_mm or rotation_deg.")
        placement = copy.deepcopy(inst["placement"])
        for key in ("position_mm", "rotation_deg"):
            if key in op:
                if op["mode"] == "delta":
                    placement[key] = [
                        round(a + b, 4) for a, b in zip(placement[key], op[key], strict=True)
                    ]
                else:
                    placement[key] = list(op[key])
        placement["source"] = "user"
        placement["locked"] = bool(op.get("lock", True))
        payload = {"placements": [{"instance_id": inst["instance_id"], "placement": placement}]}
        self._push(work, plan, "placement.updated", payload)

    def _op_resize(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        target, params = op["target"], op["params"]
        if "enclosure_id" in target:
            enc = next(
                (e for e in work["enclosures"] if e["enclosure_id"] == target["enclosure_id"]), None
            )
            if enc is None:
                raise _bad(
                    "E_INVALID_EDIT", f"No enclosure {target['enclosure_id']} in this build."
                )
            if enc.get("kind") != "generated":
                raise _bad(
                    "E_INVALID_EDIT",
                    "Only a generated case can be resized; this one comes from the design.",
                )
            new = copy.deepcopy(enc)
            old_params = enc.get("params", {})
            new["params"] = {**old_params, **params}
            size = list(new.get("outer_size_mm") or [0.0, 0.0, 0.0])
            wall_delta = float(new["params"].get("wall_mm", 0) or 0) - float(
                old_params.get("wall_mm", 0) or 0
            )
            floor_delta = float(new["params"].get("floor_mm", 0) or 0) - float(
                old_params.get("floor_mm", 0) or 0
            )
            size[0] += 2 * wall_delta
            size[1] += 2 * wall_delta
            size[2] += floor_delta
            if new["params"].get("height_mm"):
                size[2] = float(new["params"]["height_mm"])
            new["outer_size_mm"] = [round(v, 3) for v in size]
            new["revision"] = int(enc.get("revision", 0)) + 1
            errors = self.schemas.errors("build.schema.json#/$defs/Enclosure", new)
            if errors:
                raise _bad("E_INVALID_EDIT", f"Bad enclosure params: {errors[0]}")
            self._push(work, plan, "enclosure.updated", {"enclosure": new})
            return
        board = next((b for b in work["boards"] if b["board_id"] == target.get("board_id")), None)
        if board is None:
            raise _bad("E_INVALID_EDIT", f"No board {target.get('board_id')} in this build.")
        extra = set(params) - {"size_mm", "thickness_mm"}
        if extra:
            raise _bad(
                "E_INVALID_EDIT",
                f"A board resize takes size_mm and thickness_mm, not {sorted(extra)}.",
            )
        new = copy.deepcopy(board)
        new.update(copy.deepcopy(params))
        new["revision"] = int(board.get("revision", 0)) + 1
        errors = self.schemas.errors("build.schema.json#/$defs/Board", new)
        if errors:
            raise _bad("E_INVALID_EDIT", f"Bad board params: {errors[0]}")
        self._push(work, plan, "board.updated", {"board": new})

    def _op_disconnect(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        conn = next(
            (c for c in work["connections"] if c["connection_id"] == op["connection_id"]), None
        )
        if conn is None:
            raise _bad("E_INVALID_EDIT", f"No connection {op['connection_id']} in this build.")
        payload = {"connection_id": conn["connection_id"], "reason": "Disconnected by user"}
        self._push(work, plan, "connection.removed", payload)

    def _new_connection_id(self, work: dict[str, Any]) -> str:
        used = {c["connection_id"] for c in work["connections"]}
        n = 1
        while f"c_user_{n}" in used:
            n += 1
        return f"c_user_{n}"

    def _kind_for(self, work: dict[str, Any], iface_type: str) -> str:
        for c in work["connections"]:
            if c["type"] == iface_type:
                return c["kind"]
        if any(r["connection_type"] == iface_type for r in self.rules):
            return "mechanical"
        return "electrical"

    def _connect(
        self,
        work: dict[str, Any],
        frm: dict[str, Any],
        to: dict[str, Any],
        plan: EditPlan,
        state: dict,
    ) -> None:
        for end in (frm, to):
            if self._inst(work, end["instance_id"]) is None:
                raise _bad("E_UNKNOWN_INSTANCE", f"No part {end['instance_id']} in this build.")
            if self._iface(work, end) is None:
                raise _bad(
                    "E_UNKNOWN_INTERFACE",
                    f"{end['instance_id']} has no interface {end['interface_id']}.",
                    subjects=[
                        {"instance_id": end["instance_id"], "interface_id": end["interface_id"]}
                    ],
                )
        a, b = self._iface(work, frm), self._iface(work, to)
        if a["type"] != b["type"]:
            raise _bad(
                "E_INCOMPATIBLE",
                f"Cannot connect {a['type']} to {b['type']}.",
                subjects=[{"instance_id": frm["instance_id"]}, {"instance_id": to["instance_id"]}],
            )
        if a.get("role") == "requires" and b.get("role") == "provides":
            frm, to = to, frm
        conn = {
            "connection_id": self._new_connection_id(work),
            "type": a["type"],
            "kind": self._kind_for(work, a["type"]),
            "from": {
                "instance_id": frm["instance_id"],
                "interface_id": frm["interface_id"],
                "index": frm.get("index"),
            },
            "to": {
                "instance_id": to["instance_id"],
                "interface_id": to["interface_id"],
                "index": to.get("index"),
            },
            "via_instance_id": None,
            "nets": [],
            "resolved": {},
            "origin": "user",
            "status": "ok",
        }
        trial = copy.deepcopy(work)
        apply_event(trial, {"type": "connection.added", "payload": {"connection": conn}})
        for ev in self.evaluate(trial, conn):
            if ev["status"] == "fail":
                raise Reject(
                    error_obj(
                        "E_INCOMPATIBLE",
                        self._fill(ev["rule"]["fail_short"], ev["values"]),
                        stage="edit",
                        subjects=[{"instance_id": ev["requirer"]}, {"instance_id": ev["provider"]}],
                        details={"rule_id": ev["rule"]["rule_id"]},
                    ),
                    failed_checks=[self._fail_result(ev, short=False)],
                )
            if ev["rule"].get("report") == "always":
                state["checks"].append(self._pass_result(ev))
        self._push(work, plan, "connection.added", {"connection": conn})

    def _op_connect(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        self._connect(work, op["from"], op["to"], plan, state)

    def _op_add(
        self, work: dict[str, Any], op: dict[str, Any], plan: EditPlan, state: dict
    ) -> None:
        part_id = op["part_id"]
        card = self.catalog.card(part_id)
        if card is None or self.catalog.part(part_id) is None:
            raise _bad(
                "E_UNKNOWN_PART",
                f"No part {part_id} in the catalog.",
                subjects=[{"part_id": part_id}],
            )
        slot_id = op.get("slot_id")
        if slot_id is not None and self._slot(work, slot_id) is None:
            raise _bad("E_INVALID_EDIT", f"No slot {slot_id} in this build.")
        function = self.catalog.primary_function(part_id)
        if slot_id is None:
            slot = next((s for s in work["slots"] if s.get("function_id") == function), None)
            slot_id = slot["slot_id"] if slot else None
        quantity = int(op.get("quantity", 1))
        if quantity > 1:
            raise _bad(
                "E_INVALID_EDIT",
                "Adding an arrayed part (quantity > 1) needs a layout; add one at a time.",
            )
        stem = re.sub(r"[^a-z0-9]+", "_", part_id.split(":")[-1].lower()).strip("_")[:40] or "part"
        used = {p["instance_id"] for p in work["parts"]}
        n = 1
        while f"u_{stem}_{n}" in used:
            n += 1
        instance_id = f"u_{stem}_{n}"
        part = {
            "instance_id": instance_id,
            "part_id": part_id,
            "slot_id": slot_id,
            "label": card["display_name"][:60],
            "quantity": 1,
            "side": op.get("side", "none"),
            "color": None,
            "placement": {
                "mode": "single",
                "position_mm": [0.0, 0.0, 0.0],
                "rotation_deg": [0, 0, 0],
                "source": "user",
                "locked": False,
            },
            "card": copy.deepcopy(card),
            "assets": copy.deepcopy(self.catalog.part(part_id).get("assets", [])),
            "origin": "user",
            "status": "ok",
        }
        self._push(work, plan, "part.added", {"part": part})
        for iface in self.catalog.interfaces(part_id):
            if iface.get("role") != "requires":
                continue
            for other in work["parts"]:
                if other["instance_id"] == instance_id:
                    continue
                prov = next(
                    (
                        i
                        for i in self.catalog.interfaces(other["part_id"])
                        if i.get("type") == iface.get("type") and i.get("role") == "provides"
                    ),
                    None,
                )
                if prov is None:
                    continue
                frm = {
                    "instance_id": other["instance_id"],
                    "interface_id": prov["id"],
                    "index": None,
                }
                to = {"instance_id": instance_id, "interface_id": iface["id"], "index": None}
                try:
                    self._connect(work, frm, to, plan, state)
                except Reject:
                    continue
                break

    # ---- labels and entry point -----------------------------------------
    def label(self, work: dict[str, Any], ops: list[dict[str, Any]]) -> str:
        kinds = {op["op"] for op in ops}
        if len(kinds) > 1:
            return f"Applying {len(ops)} changes"
        kind = ops[0]["op"]
        inst = (
            self._inst(work, ops[0].get("instance_id", "")) if ops[0].get("instance_id") else None
        )
        base, side = phrase(inst["label"]) if inst and inst.get("label") else ("part", None)
        if kind == "swap_part":
            return f"Swapping {lower_first(base)}"
        if kind == "remove_part":
            return f"Removing the {side + ' ' if side else ''}{base}"
        if kind == "recolor":
            return f"Recoloring the {lower_first(base) if inst else 'case'}"
        if kind == "palette":
            return "Recoloring the shell"
        if kind == "move":
            return f"Moving the {side + ' ' if side else ''}{base}"
        if kind == "resize":
            return (
                "Resizing the case" if "enclosure_id" in ops[0]["target"] else "Resizing the board"
            )
        if kind == "add_part":
            card = self.catalog.card(ops[0]["part_id"])
            return f"Adding {card['display_name']}" if card else "Adding a part"
        if kind == "connect":
            return "Connecting parts"
        return "Disconnecting parts"

    def _push(
        self, work: dict[str, Any], plan: EditPlan, msg_type: str, payload: dict[str, Any]
    ) -> None:
        plan.events.append((msg_type, copy.deepcopy(payload)))
        apply_event(work, {"type": msg_type, "payload": payload})

    def plan(
        self, build: dict[str, Any], ops: list[dict[str, Any]], base_revision: int | None
    ) -> EditPlan:
        work = copy.deepcopy(build)
        plan = EditPlan(label=self.label(work, ops)[:80])
        try:
            if base_revision is not None and base_revision != build["revision"]:
                raise _bad(
                    "E_STALE_REVISION",
                    f"Edit was made on revision {base_revision}; the build is at revision "
                    f"{build['revision']}.",
                    details={"base_revision": base_revision, "revision": build["revision"]},
                )
            state: dict[str, Any] = {"checks": []}
            handlers = {
                "swap_part": self._op_swap,
                "remove_part": self._op_remove,
                "recolor": self._op_recolor,
                "palette": self._op_palette,
                "move": self._op_move,
                "resize": self._op_resize,
                "disconnect": self._op_disconnect,
                "connect": self._op_connect,
                "add_part": self._op_add,
            }
            for op in ops:
                handlers[op["op"]](work, op, plan, state)
            if state["checks"]:
                # Last result per check_key, in first-seen order.
                by_key: dict[str, dict[str, Any]] = {}
                for result in state["checks"]:
                    by_key[result["check_key"]] = result
                self._push(work, plan, "check.result", {"results": list(by_key.values())})
        except Reject as rej:
            plan.events = []
            plan.rejection = rej
        return plan
