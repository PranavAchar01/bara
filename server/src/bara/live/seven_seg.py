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
