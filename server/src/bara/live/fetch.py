"""Resolve a required need to a part: curated catalog, KiCad generated tier, LCSC fetch.

The LCSC step runs ``catalog_build.fetch_lcsc`` (``--mpn``) in a subprocess under uv, which
downloads the symbol, footprint and 3D model and appends a row to
``data/catalog/fetched/fetched.jsonl``. Results are cached there (a later build finds the row
without the network) and misses are remembered for the life of the process. A build never
waits more than ``TOTAL_BUDGET_S`` on the network; a fetch that fails or times out returns
None and the caller turns that into a failing check.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from bara.live.completeness import Need

log = logging.getLogger(__name__)

SERVER = Path(__file__).resolve().parents[3]
FETCHED_JSONL = SERVER / "data/catalog/fetched/fetched.jsonl"
PER_FETCH_S = 25.0
TOTAL_BUDGET_S = 140.0
BUDGET_PER_NEED_S = 20.0  # a device with many parts to find gets time for each of them
MISS_TTL_S = 600.0
SUFFIX_MAX = 4  # package + reel letters a vendor appends to a KiCad symbol name (TRG1, DSGR)
UV_ARGS = ("--with", "easyeda2kicad", "--with", "trimesh", "--with", "numpy")

# (term, function) -> monotonic time of the last miss
_MISSES: dict[tuple[str, str], float] = {}

Cli = Callable[[str, str, float], tuple[int, str]]

# Composed parts: when no single part is found, a function is met from generic KiCad
# primitives. Keyed by component vocabulary in the block's words, never by device. Each entry
# is (pattern, recipe name, [("sym" | "fp", exact KiCad name), ...]) tried in order.
RECIPES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (r"\b(fuse|polyfuse|overcurrent)\b", "SMD fuse", (("fp", "Fuse_1206_3216Metric"),)),
    (
        r"\b(esd|tvs|transient|surge)\b",
        "TVS protection array",
        (("sym", "USBLC6-2SC6"), ("sym", "SP0503BAHT"), ("sym", "TVS0500DRV")),
    ),
    (
        r"\b(iec|c14|c8|mains (inlet|input)|power inlet)\b",
        "IEC mains inlet",
        (("fp", "Conn_C14_Receptacle_RightAngle_Schurter_DD21.01xx"),),
    ),
    (
        r"\b(encoder|scroll wheel|rotary)\b",
        "rotary encoder",
        (("fp", "RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm"),),
    ),
    (r"\b(buzzer|beeper|piezo)\b", "buzzer", (("fp", "Buzzer_12x9.5RM7.6"),)),
    (
        # an off-board electromechanical load is wired to the board, as real products do
        r"\b(motor|rumble|vibration|haptic|erm|lra|fan|pump|solenoid|speaker|led strip)\b",
        "wire-to-board connector for an off-board load",
        (("fp", "JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical"),),
    ),
    (
        r"\b(bi-?colou?r|dual[- ]colou?r|two[- ]colou?r)\b",
        "bicolor LED",
        (("fp", "LED_LiteOn_LTST-C19HE1WT"), ("fp", "LED_Kingbright_AAA3528ESGCT")),
    ),
    (r"\b(leds?|indicator|status light)\b", "indicator LED", (("fp", "LED_0603_1608Metric"),)),
    (
        r"\b(tactile|push ?buttons?|buttons?|bumper switch(es)?|keys?)\b",
        "tactile switch",
        (("fp", "SW_SPST_TL3342"), ("fp", "SW_Push_1P1T_NO_CK_KMR2")),
    ),
)


# The function families each recipe can serve. A block's words may mention a primitive (a TFT
# "with LED backlight", a "button debounce IC") while the block itself is a panel or a chip;
# the block's function decides, so a screen is never met by an LED or a driver by a switch.
RECIPE_FAMILIES: dict[str, tuple[str, ...]] = {
    "SMD fuse": ("power.", "interconnect.", "protect"),
    "TVS protection array": ("power.", "interconnect.", "comm.", "protect"),
    "IEC mains inlet": ("power.",),
    "rotary encoder": ("input.",),
    "buzzer": ("output.buzzer", "output.speaker", "output.sound", "output.audio"),
    "wire-to-board connector for an off-board load": ("output.", "actuator."),
    "bicolor LED": ("display.indicator", "output.light", "output.led", "indicator"),
    "indicator LED": ("display.indicator", "output.light", "output.led", "indicator"),
    "tactile switch": ("input.",),
}
# a block named as a chip or a panel is never a stock primitive, whatever it drives or lights
NOT_PRIMITIVE = re.compile(
    r"\b(driver|controller|boost|regulator|ldo|charger|amplifier|amp|gauge|ic|chip|"
    r"display|screen|lcd|tft|oled|panel|module|sensor|codec|converter)\b"
)


# recipes whose primitive is the whole part: tried before an LCSC download, not after
STOCK_FIRST = frozenset({"SMD fuse", "bicolor LED", "indicator LED", "tactile switch"})


def recipe_for(need: Need) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    words = f"{need.label} {need.requirement}".lower()
    for pattern, name, steps in RECIPES:
        if not re.search(pattern, words):
            continue
        families = RECIPE_FAMILIES.get(name, ())
        if need.function_id and families and not need.function_id.startswith(families):
            continue  # the words name a primitive the block only mentions
        if name in STOCK_FIRST and NOT_PRIMITIVE.search(need.label.lower()):
            continue  # a chip or panel named after what it drives is not that primitive
        return name, steps
    return None


def stock_primitive(need: Need) -> bool:
    """The need is a generic part the KiCad library itself carries (no MPN needed)."""
    found = recipe_for(need)
    return found is not None and found[0] in STOCK_FIRST and not need.mechanical


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _names_part(query: str, name: str) -> bool:
    """A KiCad symbol answers a part number that is its name or its name plus a short
    package/packing suffix (DRV8833PWPR is the DRV8833PWP on a reel, AP2112K-3.3TRG1 the
    AP2112K-3.3). A suffix that continues a number names another part (ATmega32 is not
    the ATmega328), so it must start with a letter when the name ends in a digit."""
    q, n = slug(query).replace("_", ""), slug(name).replace("_", "")
    if not q:
        return False
    if q in n:
        return True
    rest = q[len(n) :]
    return (
        len(n) >= 6
        and q.startswith(n)
        and 0 < len(rest) <= SUFFIX_MAX
        and not (n[-1].isdigit() and rest[0].isdigit())
    )


def stock_symbol(
    search: Callable[..., list[dict[str, Any]]], mpn: str, rejected: Iterable[str] = ()
) -> dict[str, Any] | None:
    """The KiCad library symbol (with a usable footprint) that a part number names, or None."""
    # the index matches whole words: a part number with a packing suffix is also looked up
    # without it
    stems = [mpn] + [mpn[:-k] for k in range(1, SUFFIX_MAX + 1) if len(mpn) - k >= 6]
    hits: list[dict[str, Any]] = []
    for stem in stems:
        try:
            hits += search(stem, kind="symbol", limit=10)
        except Exception:
            log.exception("generated search failed for %r", stem)
    skip = set(rejected)
    ok = [
        p
        for p in hits
        if p["part_id"].startswith("kicadgen:")
        and p.get("fp_ok")
        and p["part_id"] not in skip
        and _names_part(mpn, p.get("name") or p.get("display_name") or "")
    ]
    # the longest name is the closest variant (DRV8833PWP, not DRV8833PW)
    return max(ok, key=lambda p: len(slug(p.get("name") or ""))) if ok else None


def name_slug(part: dict[str, Any]) -> str:
    return slug(f"{part.get('part_id', '')} {part.get('display_name', '')}")


def name_hit(part: dict[str, Any], words: tuple[str, ...]) -> bool:
    have = name_slug(part)
    return any(slug(w) and slug(w) in have for w in words)


def run_cli(term: str, function: str, timeout_s: float) -> tuple[int, str]:
    """The real fetcher: uv run ... python -m catalog_build.fetch_lcsc --mpn TERM."""
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    cmd = [uv, "run", *UV_ARGS, "python", "-m", "catalog_build.fetch_lcsc"]
    flag, _, value = term.partition(":") if term.startswith("keyword:") else ("mpn", "", term)
    cmd += [f"--{flag}", value, "--function", function]
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, term is passed as one argument
            cmd, cwd=SERVER, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 124, f"{type(exc).__name__}: {exc}"
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def read_fetched(path: Path = FETCHED_JSONL) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


class Overlay:
    """A part source plus parts added during a run (fetched, generated)."""

    def __init__(self, base: Any) -> None:
        self.base = base
        self.name = base.name
        self.extra: dict[str, dict[str, Any]] = {}

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.base, attr)

    def add(self, part: dict[str, Any]) -> None:
        self.extra[part["part_id"]] = part

    def get_part(self, part_id: str) -> dict[str, Any]:
        if part_id in self.extra:
            return self.extra[part_id]
        return self.base.get_part(part_id)

    def query(
        self, function: Any = None, facets: Any = None, interfaces: Any = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        found = list(self.base.query(function, facets, interfaces, limit))
        have = {p["part_id"] for p in found}
        for part in self.extra.values():
            fids = {f.get("function_id") for f in part.get("functions", [])}
            if part["part_id"] not in have and (not function or function in fids):
                found.append(part)
        return found[:limit]


def as_overlay(source: Any) -> Overlay:
    return source if isinstance(source, Overlay) else Overlay(source)


class Resolver:
    """Finds a part for a need the catalog does not serve."""

    def __init__(
        self,
        source: Overlay,
        cli: Cli | None = None,
        fetched_path: Path = FETCHED_JSONL,
        budget_s: float = TOTAL_BUDGET_S,
    ) -> None:
        self.source = source
        self.cli = cli or run_cli
        self.path = fetched_path
        self.deadline = time.monotonic() + budget_s
        self.notes: dict[str, str] = {}
        self.rejected: set[str] = set()  # parts a spec check turned down: never offered again

    # curated pool for a need: the function's parts and any part named for it
    def pool(self, need: Need) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        if need.by_function:
            for p in self.source.query(function=need.function_id, limit=500):
                found[p["part_id"]] = p
        search = getattr(self.source, "search", None)
        words = tuple(need.names) + tuple(need.terms)
        for word in words:
            if search is not None:
                try:
                    hits = search(word, limit=12)
                except Exception:  # a broken index must not end the build
                    log.exception("part search failed for %r", word)
                    hits = []
            else:
                hits = [p for p in self.source.query(limit=2000) if name_hit(p, (word,))]
            for p in hits:
                if p.get("tier") == "kicad_generated" or p["part_id"].startswith("kicadgen:"):
                    continue
                if name_hit(p, (word,)):
                    found[p["part_id"]] = p
        for p in self.source.extra.values():
            if p["part_id"] not in found and name_hit(p, words) and self._serves(p, need):
                found[p["part_id"]] = p
        # parts fetched from LCSC on earlier runs are not offered here: a missing need tries
        # the stock KiCad library first and only then that cache (resolve_missing)
        return [p for p in found.values() if p["part_id"] not in self.rejected]

    @staticmethod
    def _serves(part: dict[str, Any], need: Need) -> bool:
        return need.function_id in {f.get("function_id") for f in part.get("functions", [])}

    def generated(self, need: Need) -> dict[str, Any] | None:
        """A KiCad library part with a usable footprint, by symbol name."""
        search = getattr(self.source, "search", None)
        if search is None:
            return None
        for q in need.kicad:
            found = stock_symbol(search, q, self.rejected)
            if found is not None:
                return self._accept(found, need)
        return None

    def composed(self, need: Need) -> dict[str, Any] | None:
        """The last resort before a required need fails: a generic KiCad primitive that meets
        the function (RECIPES), tagged so the audit chain shows it was composed."""
        found = recipe_for(need)
        search = getattr(self.source, "search", None)
        if found is None or search is None or need.mechanical:
            return None  # recipes are electrical; the case makes a touched mechanical part
        name, steps = found
        for kind, exact in steps:
            try:
                hits = search(exact, kind="symbol" if kind == "sym" else "footprint", limit=10)
            except Exception:
                log.exception("recipe search failed for %r", exact)
                continue
            for p in hits:
                if not p["part_id"].startswith("kicadgen:") or not p.get("fp_ok"):
                    continue
                if p["part_id"] in self.rejected or not p["part_id"].endswith(":" + exact):
                    continue
                part = self._accept(p, need)
                part["composed"] = name
                return part
        self.notes[need.key] = (
            self.notes.get(need.key, "") + f"; recipe {name!r}: no usable KiCad primitive"
        ).lstrip("; ")
        return None

    def _accept(self, part: dict[str, Any], need: Need) -> dict[str, Any]:
        part = self._retag(part, need)
        try:
            from bara.kicad_generated import ensure_glb  # type: ignore[import-not-found]

            ensure_glb(part["part_id"])
        except Exception as exc:  # no 3D model is a warning on the part, not a failure
            log.info("no 3D model for %s: %s", part["part_id"], exc)
        self.source.add(part)
        return part

    def fetch(self, need: Need) -> dict[str, Any] | None:
        """Search + download from LCSC. Returns the new catalog row, or None with a note."""
        if need.mechanical:
            # LCSC sells electronics: "scroll wheel" finds an encoder, and the part number a
            # cap names is the stick it fits. The case makes a touched mechanical part.
            self.notes[need.key] = "made by the case"
            return None
        reasons: list[str] = []
        terms = list(need.terms)
        # no MPN worked (or none was named): search by what the block is, in words
        words = re.sub(r"[^\w/.+-]+", " ", f"{need.label} {need.requirement}").strip()
        terms.append("keyword:" + re.sub(r"\s+", " ", words)[:60])
        for term in terms:
            cached = self._cached(term, need)
            if cached is not None:
                self.source.add(cached)
                return cached
            key = (term, need.function_id)
            if time.monotonic() - _MISSES.get(key, -1e9) < MISS_TTL_S:
                reasons.append(f"{term}: no LCSC match (cached miss)")
                continue
            left = self.deadline - time.monotonic()
            if left < 3.0:
                reasons.append("fetch time budget used up")
                break
            before = {p["part_id"] for p in read_fetched(self.path)}
            rc, out = self.cli(term, need.function_id, min(PER_FETCH_S, left))
            rows = [p for p in read_fetched(self.path) if p["part_id"] not in before]
            if rc == 0 and not rows:  # the row already existed and was rewritten
                pid = out.split()[0] if out.split() else ""
                rows = [p for p in read_fetched(self.path) if p["part_id"] == pid]
            if rc == 0 and rows and rows[-1]["part_id"] not in self.rejected:
                part = rows[-1]
                self.source.add(part)
                return part
            _MISSES[key] = time.monotonic()
            reasons.append(f"{term}: " + (out.strip().splitlines() or ["failed"])[-1][:120])
        self.notes[need.key] = "; ".join(reasons) or "no search terms"
        return None

    def _cached(self, term: str, need: Need) -> dict[str, Any] | None:
        named = not term.startswith("keyword:")
        for p in read_fetched(self.path):
            if p["part_id"] in self.rejected:
                continue
            if slug(term).replace("_", "") not in name_slug(p).replace("_", ""):
                continue
            if self._serves(p, need):
                return p
            # a row keeps the function it was first fetched for; the part number this block
            # named is the part it asked for, whatever that function was
            if named and slug(term) and slug(term) in slug(p.get("mpn") or ""):
                return self._retag(p, need)
        return None

    @staticmethod
    def _retag(part: dict[str, Any], need: Need) -> dict[str, Any]:
        part = dict(part)
        fids = [f for f in part.get("functions", []) if f.get("function_id") != need.function_id]
        part["functions"] = [{"function_id": need.function_id, "primary": True}, *fids]
        return part
