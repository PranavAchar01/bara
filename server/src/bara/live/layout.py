"""Brief -> key layout (Ergogen-style points), keep-outs and the controller pin budget.

Generic: the same code lays out a split, a unibody board and a macropad from the brief's
counts. Hand-set constants are listed in ``CONSTANTS`` with where they come from; the
report and the board stage read them from there so nothing is hidden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

PITCH_MM = 19.05  # 0.75 in key unit, the MX and Choc-spaced standard (SPEC 3.3)

CONSTANTS: dict[str, dict[str, Any]] = {
    "column_stagger_u": {
        # Outer (pinky) to inner (index) column offsets, in key units, for column-staggered
        # splits. Hand-set from typical finger lengths; Ergogen's default 'stagger' is 0.25u.
        "value": [0.5, 0.5, 0.25, 0.0, 0.25, 0.375],
        "source": "hand-set (typical finger-length stagger)",
    },
    "thumb_fan_deg": {"value": 8.0, "source": "hand-set"},
    "thumb_keys_default": {"value": {"18+": 3, "else": 2}, "source": "hand-set"},
    "rows_default": {"value": {"split": 3, "unibody": 4, "macropad": 4}, "source": "hand-set"},
    "unibody_default_cols": {"value": 12, "source": "hand-set (ortholinear 40%)"},
    "pin_cost": {
        # Pins a peripheral needs on the controller when its part record does not say.
        # Bus pins (I2C SDA/SCL, SPI SCK/MOSI/MISO) are shared and counted once per bus.
        "value": {
            "i2c_bus": 2,
            "spi_bus": 3,
            "spi_cs": 1,
            "uart": 2,
            "encoder": 2,
            "trackball_motion": 1,
            "epaper_ctrl": 3,
            "split_link_wired": 1,
            "analog": 1,
            "motor_dc": 2,
            "button": 1,
            "rgb_led": 1,
        },
        "source": "protocol pin counts; encoder A/B, e-paper DC/RST/BUSY, PMW33xx MOTION",
    },
}


@dataclass
class Keepout:
    feature: str
    side: str
    center_u: tuple[float, float]
    size_mm: tuple[float, float]


@dataclass
class Half:
    side: str  # left | right | none
    rows: int
    cols: int
    thumbs: int
    keys: list[dict[str, Any]] = field(default_factory=list)
    keepouts: list[Keepout] = field(default_factory=list)

    @property
    def matrix(self) -> tuple[int, int]:
        rows = self.rows + (1 if self.thumbs else 0)
        return rows, max(self.cols, self.thumbs)

    @property
    def width_u(self) -> float:
        return max((k["x_u"] + 1 for k in self.keys), default=0.0)

    @property
    def height_u(self) -> float:
        return max((k["y_u"] + 1 for k in self.keys), default=0.0)


@dataclass
class KeyboardPlan:
    style: str
    halves: list[Half]
    key_count: int
    log: list[str] = field(default_factory=list)

    def layout_json(self, half: Half, layout_id: str, name: str) -> dict[str, Any]:
        return {
            "layout_id": layout_id,
            "name": name[:80],
            "pitch_x_mm": PITCH_MM,
            "pitch_y_mm": PITCH_MM,
            "keys": half.keys,
        }


def _stagger(cols: int) -> list[float]:
    profile = CONSTANTS["column_stagger_u"]["value"]
    if cols <= len(profile):
        return profile[len(profile) - cols :]
    return [profile[0]] * (cols - len(profile)) + profile


def _half_keys(n: int, rows: int, cols: int, thumbs: int, stagger: bool, mirror: bool) -> list:
    main = n - thumbs
    offsets = _stagger(cols) if stagger else [0.0] * cols
    positions = [(r, c) for r in range(rows) for c in range(cols)]
    # Drop surplus positions from the outer column's bottom upward, then the next column.
    surplus = rows * cols - main
    drop: set[tuple[int, int]] = set()
    col = 0
    while surplus > 0 and col < cols:
        for r in range(rows - 1, -1, -1):
            if surplus == 0:
                break
            drop.add((r, col))
            surplus -= 1
        col += 1
    keys: list[dict[str, Any]] = []
    for r, c in positions:
        if (r, c) in drop:
            continue
        x = (cols - 1 - c) if mirror else c
        keys.append({"x_u": float(x), "y_u": round(r + offsets[c], 4), "matrix": [r, c]})
    fan = CONSTANTS["thumb_fan_deg"]["value"]
    base_y = rows + max(offsets[-1] if offsets else 0.0, 0.0) + 0.15
    for i in range(thumbs):
        x = cols - thumbs + i + 0.5
        y = base_y + 0.1 * i
        r = fan * i
        if mirror:
            x = (cols - 1) - x
            r = -r
        key = {"x_u": round(x, 4), "y_u": round(y, 4), "matrix": [rows, i]}
        if r:
            key.update({"r_deg": r, "rx_u": round(x + 0.5, 4), "ry_u": round(y + 0.5, 4)})
        keys.append(key)
    keys.sort(key=lambda k: (k["matrix"][0], k["x_u"]))
    for i, key in enumerate(keys):
        key["i"] = i
    return [{"i": k.pop("i"), **k} for k in keys]


def plan_keyboard(brief: dict[str, Any]) -> KeyboardPlan | None:
    style = brief.get("layout_style")
    if style not in ("split", "unibody", "macropad"):
        return None
    log: list[str] = []
    rows_default = CONSTANTS["rows_default"]["value"][style]
    rows = int(brief.get("rows") or rows_default)
    halves_n = 2 if style == "split" else 1
    key_count = brief.get("key_count")
    if not key_count:
        cols = int(brief.get("cols") or CONSTANTS["unibody_default_cols"]["value"])
        key_count = rows * cols * halves_n if style != "split" else 36
        log.append(f"key count not given; used {key_count}")
    key_count = int(key_count)
    per_half = [key_count // halves_n + (1 if i < key_count % halves_n else 0) for i in range(2)]
    per_half = per_half[:halves_n]
    halves: list[Half] = []
    for idx, n in enumerate(per_half):
        if style == "split":
            thumbs = brief.get("thumb_keys")
            if thumbs is None:
                thumbs = 3 if n >= 18 else 2
            thumbs = int(thumbs)
            cols = int(brief.get("cols") or math.ceil((n - thumbs) / rows))
            side = "left" if idx == 0 else "right"
            stagger = brief.get("stagger") != "ortho"
        else:
            thumbs = 0
            cols = int(brief.get("cols") or math.ceil(n / rows))
            side = "none"
            stagger = brief.get("stagger") == "column"
        keys = _half_keys(n, rows, cols, thumbs, stagger, mirror=(side == "right"))
        halves.append(Half(side=side, rows=rows, cols=cols, thumbs=thumbs, keys=keys))
        log.append(
            f"{side if side != 'none' else 'board'}: {n} keys = {rows}x{cols} grid"
            + (f" + {thumbs} thumb" if thumbs else "")
            + (" column-staggered" if stagger else " ortholinear")
        )
    plan = KeyboardPlan(style=style, halves=halves, key_count=key_count, log=log)
    _keepouts(plan, brief)
    return plan


def feature_sides(brief: dict[str, Any], kind: str, split: bool) -> list[str]:
    """One entry per physical copy of a feature: which half it sits on."""
    out: list[str] = []
    for feature in brief.get("features", []):
        if feature["kind"] != kind:
            continue
        count = max(1, int(feature.get("count") or 1))
        side = feature.get("side")
        if not split:
            out += ["none"] * count
            continue
        if side in ("left", "right"):
            out += [side] * count
        elif count >= 2:
            out += ["left", "right"] * (count // 2) + ["left"] * (count % 2)
        else:
            out += ["right" if kind == "trackball" else "left"]
    return out


def _keepouts(plan: KeyboardPlan, brief: dict[str, Any]) -> None:
    split = plan.style == "split"
    by_side = {h.side: h for h in plan.halves}

    def half_for(side: str) -> Half:
        return by_side.get(side) or plan.halves[0]

    sizes = {"knob": (14.0, 14.0), "trackball": (38.0, 38.0), "screen": (38.0, 14.0)}
    for kind in ("knob", "trackball", "screen"):
        positions = [
            (f.get("position") or "").lower()
            for f in brief.get("features", [])
            if f["kind"] == kind
        ]
        for n, side in enumerate(feature_sides(brief, kind, split)):
            half = half_for(side)
            where = positions[min(n, len(positions) - 1)] if positions else ""
            if kind == "trackball" or "thumb" in where:
                inner = half.width_u if half.side != "right" else -1.0
                center = (inner + (0.5 if half.side != "right" else -0.5), half.height_u + 0.3)
            elif "top" in where or kind == "screen":
                x = -1.0 if ("left" in where or half.side == "left") else half.width_u
                if kind == "screen":
                    x = half.width_u if half.side != "right" else -1.0
                center = (x + 0.5, 0.5)
            else:
                center = (half.width_u + 0.5, 0.5 + n)
            half.keepouts.append(Keepout(kind, half.side, center, sizes[kind]))
            plan.log.append(
                f"keep-out {kind} on {half.side}: {sizes[kind][0]:.0f}x{sizes[kind][1]:.0f} mm "
                f"at {center[0]:.2f},{center[1]:.2f} u ({where or 'default spot'})"
            )


def pin_need(
    half: Half | None, peripherals: list[dict[str, Any]], wired_split: bool
) -> tuple[int, list[str]]:
    """GPIO a controller needs for its keys and the peripherals wired to it."""
    cost = CONSTANTS["pin_cost"]["value"]
    items: list[str] = []
    total = 0
    if half is not None and half.keys:
        rows, cols = half.matrix
        total += rows + cols
        items.append(f"matrix {rows}x{cols} = {rows + cols}")
    buses: set[str] = set()
    for p in peripherals:
        kind = p["kind"]
        part = p.get("part") or {}
        ifaces = [i for i in part.get("interfaces", []) if i.get("role") == "requires"]
        types = {i.get("type") for i in ifaces}
        n = 0
        if "i2c" in types or "qwiic" in types:
            if "i2c" not in buses:
                n += cost["i2c_bus"]
                buses.add("i2c")
        if "spi" in types:
            if "spi" not in buses:
                n += cost["spi_bus"]
                buses.add("spi")
            n += cost["spi_cs"]
        gpio = [i for i in ifaces if i.get("type") == "gpio"]
        for g in gpio:
            count = (g.get("params") or {}).get("count") or len(g.get("pins") or []) or 1
            n += int(count)
        n += sum(cost["analog"] for i in ifaces if i.get("type") == "analog")
        if not ifaces:
            n += {
                "knob": cost["encoder"],
                "trackball": cost["spi_bus"] * ("spi" not in buses)
                + cost["spi_cs"]
                + cost["trackball_motion"],
                "screen_epaper": cost["spi_bus"] * ("spi" not in buses)
                + cost["spi_cs"]
                + cost["epaper_ctrl"],
                "screen": cost["i2c_bus"] * ("i2c" not in buses),
                "sensor": cost["i2c_bus"] * ("i2c" not in buses),
                "motor": cost["motor_dc"],
                "analog_sensor": cost["analog"],
                "button": cost["button"],
                "led": cost["rgb_led"],
            }.get(kind, 0)
            if kind in ("trackball", "screen_epaper"):
                buses.add("spi")
            if kind in ("screen", "sensor"):
                buses.add("i2c")
        if n:
            items.append(f"{p['label']} {n}")
            total += n
    if wired_split:
        total += cost["split_link_wired"]
        items.append(f"split link {cost['split_link_wired']}")
    return total, items
