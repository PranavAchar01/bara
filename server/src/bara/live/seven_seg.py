"""Seven-segment LED displays: what a block asks for and what a library part is, read from
words. The KiCad index tags every digit module display.lcd_char and states digits, colour and
polarity only in its description ("4 digit 7 segment high efficiency red LED, common anode"),
so the match reads those words instead of expecting facets the entries do not carry."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

FUNCTION_ID = "display.seven_segment"

_NUMBER_WORDS = {
    "single": 1,
    "one": 1,
    "double": 2,
    "dual": 2,
    "two": 2,
    "triple": 3,
    "three": 3,
    "quad": 4,
    "four": 4,
    "five": 5,
    "six": 6,
    "eight": 8,
}
_DIGITS = re.compile(
    r"\b(\d+|" + "|".join(_NUMBER_WORDS) + r")[\s-]*(?:and a half[\s-]*)?digits?\b", re.I
)
_COLOURS = ("red", "green", "yellow", "orange", "blue", "white", "amber")
_HEIGHT = re.compile(r"(\d*\.\d+|\d+)\s*(?:\"|in\b|inch)", re.I)
_NAME_HEIGHT = re.compile(r"^[A-Z]{2}(\d{2})-\d", re.I)  # Kingbright CA56-12EWA is 0.56 in
_LCD = re.compile(r"\blcd\b|liquid crystal|reflective|transmissive", re.I)
_SIXTEEN = re.compile(r"1[46][\s-]*segment|alphanumeric|dot[\s-]*matrix", re.I)


@dataclass(frozen=True)
class Want:
    digits: int | None = None
    colour: str | None = None
    polarity: str | None = None  # "anode" | "cathode"
    height_in: float | None = None
    colon: bool = False


def _count(token: str) -> int | None:
    token = token.lower()
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token)


def digits_of(text: str) -> int | None:
    m = _DIGITS.search(text or "")
    return _count(m.group(1)) if m else None


def _colour(text: str) -> str | None:
    low = (text or "").lower()
    return next((c for c in _COLOURS if re.search(rf"\b{c}\b", low)), None)


def _polarity(text: str) -> str | None:
    m = re.search(r"common[\s-]*(anode|cathode)", (text or "").lower())
    return m.group(1) if m else None


def want_from(text: str) -> Want:
    """What a block's label and requirement ask of the display."""
    height = None
    for m in _HEIGHT.finditer(text or ""):
        height = float(m.group(1))
        break
    return Want(
        digits=digits_of(text),
        colour=_colour(text),
        polarity=_polarity(text),
        height_in=height,
        colon="colon" in (text or "").lower(),
    )


def _blob(part: dict[str, Any]) -> str:
    return " ".join(
        str(part.get(k) or "") for k in ("display_name", "description", "summary", "descr")
    )


def is_led_digit_module(part: dict[str, Any]) -> bool:
    """A 7-segment LED module (not LCD glass, a 16-segment or dot-matrix unit, or a driver)."""
    blob = _blob(part)
    if _LCD.search(blob) or _SIXTEEN.search(blob):
        return False
    if (part.get("facets") or {}).get("display_type") == "seven_segment":
        return True
    return bool(re.search(r"7[\s-]*segment|seven[\s-]*segment", blob, re.I))


def have_digits(part: dict[str, Any]) -> int | None:
    return digits_of(_blob(part))


def have_height_in(part: dict[str, Any]) -> float | None:
    m = _NAME_HEIGHT.match(str(part.get("name") or part.get("display_name") or ""))
    if m:
        return int(m.group(1)) / 100
    m = re.search(r"(\d*\.\d+|\d+)[\s-]*(?:inch|in)\b[^,]*digit height", _blob(part), re.I)
    return float(m.group(1)) if m else None


def too_few_pins(part: dict[str, Any], digits: int) -> bool:
    """A multiplexed display of N digits needs 8 segment lines plus a common per digit."""
    pins = (part.get("facets") or {}).get("pin_count") or part.get("pins")
    if isinstance(pins, list):
        pins = len(pins)
    return bool(pins) and int(pins) < 8 + digits


def meets_digits(part: dict[str, Any], want: Want) -> bool:
    """False only on evidence: a stated other digit count, or too few pins for the digits."""
    if not want.digits:
        return True
    have = have_digits(part)
    if have is not None:
        return have == want.digits
    return not too_few_pins(part, want.digits)


def score(part: dict[str, Any], want: Want) -> float:
    """Higher is closer. Digit count is a gate (meets_digits); colour, polarity and digit
    height only rank, since a driver or a series resistor change handles each."""
    blob = _blob(part)
    s = 0.0
    if want.digits and have_digits(part) == want.digits:
        s += 4
    if want.colour and _colour(blob) == want.colour:
        s += 2
    elif not want.colour and _colour(blob) == "red":
        s += 0.3  # the usual colour of a clock or timer when none is asked
    if want.polarity and _polarity(blob) == want.polarity:
        s += 1.5
    height = have_height_in(part)
    if want.height_in and height is not None:
        s += 2 - min(2.0, abs(height - want.height_in) * 10)
    if part.get("has_model") or (part.get("facets") or {}).get("has_mesh"):
        s += 0.5
    return s


def find(
    search: Callable[..., list[dict[str, Any]]],
    text: str,
    rejected: Iterable[str] = (),
) -> dict[str, Any] | None:
    """The best KiCad-library seven-segment module for a block's words, or None."""
    want = want_from(text)
    skip = set(rejected)
    queries = [f"{want.digits} digit 7 segment"] if want.digits else []
    queries.append("7 segment led")
    seen: dict[str, dict[str, Any]] = {}
    for q in queries:
        try:
            hits = search(q, kind="symbol", limit=60)
        except Exception:  # a broken index must not end the build
            continue
        for p in hits:
            if p["part_id"].startswith("kicadgen:") and p["part_id"] not in skip:
                seen[p["part_id"]] = p
    ok = [
        p
        for p in seen.values()
        if p.get("fp_ok") and is_led_digit_module(p) and meets_digits(p, want)
    ]
    return max(ok, key=lambda p: score(p, want)) if ok else None


# ---- the driver a bare multiplexed display needs ---------------------------------------
_HAS_DRIVER = re.compile(
    r"tm16\d\d|max72\d\d|ht16k33|ht1632|ics?7218|hcms|\bi2c\b|\bspi\b|serial|\bdriver\b"
    r"|backpack",
    re.I,
)


@dataclass(frozen=True)
class Driver:
    """The segment driver chip for a display: names find it in the part source, terms are
    the MPNs to fetch from LCSC when it is not there yet."""

    key: str
    label: str
    names: tuple[str, ...]
    terms: tuple[str, ...]
    pin_kind: str  # layout.pin_need kind: the controller pins the chip's serial lines cost


# TM1637 sinks the segments and sources the digits (common-anode glass, two wires);
# MAX7219 sources the segments and sinks the digits (common-cathode glass, three wires).
TM1637 = Driver("tm1637", "TM1637 display driver", ("tm1637",), ("TM1637",), "seg_driver_2wire")
MAX7219 = Driver(
    "max7219", "MAX7219 display driver", ("max7219",), ("MAX7219CWG",), "seg_driver_3wire"
)


def needs_driver(part: dict[str, Any]) -> bool:
    """A bare multi-digit LED module: eight segment lines and a common per digit, with no
    driver chip or serial bus on it, so a controller cannot drive it from a few pins."""
    if not is_led_digit_module(part):
        return False
    if part.get("kind") == "module" or part.get("interfaces"):
        return False
    if _HAS_DRIVER.search(_blob(part)):
        return False
    digits = have_digits(part)
    if digits is None:
        pins = (part.get("facets") or {}).get("pin_count") or part.get("pins")
        if isinstance(pins, list):
            pins = len(pins)
        digits = max(0, int(pins or 0) - 8)
    return digits >= 2


def driver_for(part: dict[str, Any]) -> Driver:
    """MAX7219 for common-cathode glass, TM1637 otherwise (the module-board default)."""
    return MAX7219 if _polarity(_blob(part)) == "cathode" else TM1637


_DRIVER_CHIP = re.compile(r"tm16\d\d|max72\d\d|ht16k33|ht1632|ics?7218", re.I)


def is_driver_chip(part: dict[str, Any]) -> bool:
    """A segment-driver IC (the catalog files them under the seven-segment function)."""
    return bool(_DRIVER_CHIP.search(f"{part.get('part_id', '')} {part.get('display_name', '')}"))


def segment_index(name: str) -> int | None:
    """Segment number 1..8 (a..g, then the point) a display or driver pin name stands for."""
    n = re.sub(r"[\s_]", "", str(name)).upper()
    if len(n) == 1 and n in "ABCDEFG":
        return "ABCDEFG".index(n) + 1
    if n in ("DP", "DPX", "H"):
        return 8
    m = re.fullmatch(r"(?:SEG|SG\d?KS|SG)([A-G]|DP|\d)", n)
    if not m:
        return None
    t = m.group(1)
    return 8 if t == "DP" else "ABCDEFG".index(t) + 1 if t in "ABCDEFG" else int(t)


def digit_index(name: str) -> int | None:
    """Digit number 1.. a display's common (CA1, CC2) or a driver's grid (GRID1, DIG_0)
    stands for; the MAX7219's DIG_0 is the first digit."""
    n = re.sub(r"[\s_]", "", str(name)).upper()
    m = re.fullmatch(r"(CA|CC|COM|DIG|DIGIT|GRID|GR)(\d)", n)
    if not m:
        return None
    return int(m.group(2)) + (1 if m.group(1) == "DIG" else 0)


def names_driver_chip(need: Any, part: dict[str, Any] | None) -> bool:
    """A block (or its chosen part) that is a segment-driver chip by its words."""
    if part is not None and is_driver_chip(part):
        return True
    if need is None:
        return False
    return bool(_DRIVER_CHIP.search(" ".join([need.label, *need.names, *need.terms])))
