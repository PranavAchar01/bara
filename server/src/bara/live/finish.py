"""Finishing pass: the device's colours and materials, chosen on purpose after industrial design.

The case is clear see-through plastic with a slight tint (never a flat solid colour); what is
inside stays itself: controls share one coherent palette, a screen is dark glass with a lit
window, boards are solder-mask green or black, connectors and transducers are metal. Roles come
from each part's function id and kind, never from device names. A colour the person asked for
(brief colours: case, keycaps, accent, knob, all) wins over the palette.

Every choice is written to the build state as a `finish` record ({role, name, color, opacity,
roughness, metalness, transmission, ior, emissive, emissive_intensity}) on parts, boards and
the case (plus `node_finish` per case GLB node), and a summary on `scene.finish`.
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Curated palettes: a case tint and three control colours that sit well together and against
# the tint (primary for the largest controls, accent for action controls, quiet for the small
# ones). The tint is drawn as translucent tinted plastic (the viewer mixes it about halfway
# toward clear at low opacity), so it is a saturated mid tone that still reads as a colour once
# it is see-through, never a pale near-white. Picked per build from a hash of the prompt so a
# rebuild keeps its look.
_P = ("name", "tint", "primary", "accent", "quiet")
PALETTES: list[dict[str, str]] = [
    dict(zip(_P, row, strict=True))
    for row in (
        ("smoke", "#5E6773", "#22262C", "#E4572E", "#9AA1AA"),
        ("ice", "#4FA9D6", "#1C2733", "#F2B134", "#E8EDF2"),
        ("amber", "#E39A2D", "#2E2A26", "#C8302D", "#F1E6D3"),
        ("violet", "#8A6BD6", "#211E2A", "#F2B134", "#EDE8F7"),
        ("mint", "#3FBF8F", "#1E2B26", "#E85D75", "#F0F4F1"),
        ("berry", "#D3507E", "#2A2228", "#F4E04D", "#F5EEF1"),
        ("tangerine", "#F07A2E", "#24262B", "#2FA3C7", "#F3EEE8"),
    )
]

PCB_GREEN, PCB_BLACK = "#1E6B3A", "#14171A"


def _finish(role: str, name: str, color: str, **kw: Any) -> dict[str, Any]:
    out = {
        "role": role,
        "name": name[:60],
        "color": color.upper(),
        "opacity": 1.0,
        "roughness": 0.5,
        "metalness": 0.0,
        "transmission": 0.0,
        "ior": 1.45,
        "emissive": None,
        "emissive_intensity": 0.0,
    }
    out.update(kw)
    return out


def clear_case(tint: str) -> dict[str, Any]:
    return _finish(
        "case", "clear tinted plastic", tint, opacity=0.32, roughness=0.12, transmission=0.9,
        ior=1.49,
    )  # fmt: skip


def screen_glass() -> dict[str, Any]:
    return _finish(
        "display", "dark glass, lit window", "#0B0E12", roughness=0.06, ior=1.52,
        emissive="#9CC7FF", emissive_intensity=0.35,
    )  # fmt: skip


def control(color: str, name: str) -> dict[str, Any]:
    return _finish("control", name, color, roughness=0.45)


def metal(name: str = "brushed metal") -> dict[str, Any]:
    return _finish("metal", name, "#B9BDC3", roughness=0.32, metalness=1.0)


def connector() -> dict[str, Any]:
    return _finish("connector", "plated metal", "#C7CACE", roughness=0.25, metalness=1.0)


def pcb(color: str) -> dict[str, Any]:
    return _finish("pcb", "solder mask", color, roughness=0.55)


def other(name: str, color: str = "#2A2C30") -> dict[str, Any]:
    return _finish("other", name, color, roughness=0.6)


def palette_for(prompt: str, colours: list[dict[str, Any]] | None) -> dict[str, str]:
    """The build's palette; colours the person named replace the matching entries."""
    i = int(hashlib.sha256(prompt.strip().lower().encode()).hexdigest(), 16) % len(PALETTES)
    pal = dict(PALETTES[i])
    for c in colours or []:
        hx = str(c.get("hex") or "")
        if not HEX.match(hx):
            continue
        target = c.get("target")
        if target in ("case", "all"):
            pal["tint"] = hx
        if target in ("keycaps", "knob", "trackball", "all"):
            pal["primary"] = hx
        if target == "accent":
            pal["accent"] = hx
    return pal


def role(fn: str, kind: str) -> str:
    """The finish role of a part from its function id and catalog kind."""
    if fn.startswith("display.") and fn not in ("display.led", "display.seven_segment"):
        return "display"
    if fn.startswith(("input.", "mech.keycap", "mech.knob")) or fn in ("power.switch",):
        return "control"
    if fn.startswith(("interconnect.", "storage.")) or fn.endswith(".connector"):
        return "connector"
    if fn.startswith(("output.speaker", "output.buzzer", "output.vibration", "actuator.")):
        return "metal"
    if kind == "module" or fn.startswith("compute."):
        return "pcb"
    return "other"


def plan(build: dict[str, Any], colours: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Finish records for every part, board and case of the build, without mutating it.

    Returns {"palette", "parts": {instance_id: finish}, "boards": {board_id: finish},
    "enclosures": {enclosure_id: (finish, node_finish)}}."""
    pal = palette_for(str(build.get("prompt") or ""), colours)
    slots = {s.get("slot_id"): s for s in build.get("slots") or []}
    # control groups in slot order: the first gets the primary colour, the next the accent, the
    # rest the quiet one, so a device reads as one designed palette
    tones = [("primary", pal["primary"]), ("accent", pal["accent"]), ("quiet", pal["quiet"])]
    group_tone: dict[str, tuple[str, str]] = {}
    parts: dict[str, dict[str, Any]] = {}
    dark_board = pal["name"] in ("smoke", "violet", "berry")
    for part in build.get("parts") or []:
        card = part.get("card") or {}
        slot = slots.get(part.get("slot_id")) or {}
        fn = str(card.get("primary_function") or slot.get("function_id") or "")
        r = role(fn, str(card.get("kind") or ""))
        if r == "control":
            key = str(part.get("slot_id") or part["instance_id"])
            if key not in group_tone:
                group_tone[key] = tones[min(len(group_tone), len(tones) - 1)]
            tone, hx = group_tone[key]
            parts[part["instance_id"]] = control(hx, f"{tone} control")
        elif r == "display":
            parts[part["instance_id"]] = screen_glass()
        elif r == "connector":
            parts[part["instance_id"]] = connector()
        elif r == "metal":
            parts[part["instance_id"]] = metal()
        elif r == "pcb":
            parts[part["instance_id"]] = pcb(PCB_BLACK if dark_board else PCB_GREEN)
        else:
            parts[part["instance_id"]] = other("matte component")
    boards = {
        b["board_id"]: pcb(PCB_BLACK if dark_board else PCB_GREEN)
        for b in build.get("boards") or []
        if b.get("board_id")
    }
    case = clear_case(pal["tint"])
    caps = control(pal["primary"], "primary control (caps)")
    encs: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]]]] = {}
    for enc in build.get("enclosures") or []:
        nodes: dict[str, dict[str, Any]] = {}
        for a in enc.get("assets") or []:
            for node in a.get("nodes") or []:
                name = str(node)
                if name.endswith("_caps"):
                    nodes[name] = caps
                elif name.endswith("_glass"):
                    nodes[name] = screen_glass()
                elif name.endswith(("_tray", "_bezel")):
                    nodes[name] = case
        encs[enc["enclosure_id"]] = (case, nodes)
    palette = {
        "case": pal["tint"],
        "primary": pal["primary"],
        "accent": pal["accent"],
        "quiet": pal["quiet"],
        "pcb": PCB_BLACK if dark_board else PCB_GREEN,
    }
    return {
        "palette": palette,
        "palette_name": pal["name"],
        "case": case,
        "parts": parts,
        "boards": boards,
        "enclosures": encs,
    }


def events(
    build: dict[str, Any], colours: list[dict[str, Any]] | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """The (message type, payload) list that writes the finish into the build state."""
    fin = plan(build, colours)
    out: list[tuple[str, dict[str, Any]]] = []
    for part in build.get("parts") or []:
        f = fin["parts"].get(part["instance_id"])
        if f is not None:
            out.append(("part.updated", {"part": {**copy.deepcopy(part), "finish": f}}))
    for board in build.get("boards") or []:
        f = fin["boards"].get(board.get("board_id"))
        if f is not None:
            out.append(("board.updated", {"board": {**copy.deepcopy(board), "finish": f}}))
    for enc in build.get("enclosures") or []:
        case, nodes = fin["enclosures"][enc["enclosure_id"]]
        new = {**copy.deepcopy(enc), "finish": case, "node_finish": nodes}
        if enc.get("color_source") != "user":  # the tint the case is drawn with
            new["color"] = {"hex": case["color"], "material": "plastic", "node": None}
            new["color_source"] = "design"
        out.append(("enclosure.updated", {"enclosure": new}))
    if build.get("scene") is not None:
        scene = {
            **copy.deepcopy(build["scene"]),
            "finish": {
                "palette": fin["palette"],
                "palette_name": fin["palette_name"],
                "case": fin["case"],
            },
        }
        out.append(("scene.ready", {"scene": scene}))
    return out
