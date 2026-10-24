"""Resolve manifest refs and KiCad model paths to files on disk, with their source."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .sources import SOURCES, VENDOR_MODEL_LICENCE, Licence, Source, source_rel_url

# marbastlib README "3D Models" list: files provided by someone else, NOT covered by the
# repository licence. Matched as substrings of the model file name.
MARBASTLIB_VENDOR_MODELS = (
    "Johanson",
    "Crystal_SMD_20",
    "Everlight",
    "Sinhoo",
    "Mounting_Wuerth",
    "QFN-14_2x2",
    "Texas_",
    "UDFN1212",
    "NANOT240",
    "SK6812",
    "WS2812",
    "MHT151",
    "MJ-4PP-9",
    "FA-128",
    "MSK12C02",
    "T1A2QR",
    "ESP3020",
    "MK08A",
    "E73-2G4M08",
    "HytePro",
    "Liatris",
    "ACHSS",
    "MP2722",
    "MP3431",
    "SRP60",
    "CKST353220",
    "U-DFN2020",
    "PDFN3333",
    "RP2040-Matrix",
    "HC-PBB40C",
    "Skyloong",
    "Hotswap-Encoder",
    "SRSS",
    "TYPE-C-31",
    "USB45",
    "USB4510",
    "XUNPU",
    "holyiot",
    "seeeduino",
    "EC11",
    "SKHLL",
    "SSSS2",
)


@dataclass(frozen=True)
class Resolved:
    path: Path
    source: Source
    rel: str  # path relative to the source root

    @property
    def url(self) -> str:
        return source_rel_url(self.source, self.rel)

    @property
    def licence(self) -> Licence:
        if self.source.key == "marbastlib" and any(
            k in self.path.name for k in MARBASTLIB_VENDOR_MODELS
        ):
            return VENDOR_MODEL_LICENCE
        return self.source.licence


def _rel(src: Source, path: Path) -> str:
    return str(path.relative_to(src.root))


def resolve_footprint(ref: str) -> Resolved:
    key, _, rest = ref.partition(":")
    if key == "kicad":
        lib, _, name = rest.partition(":")
        src = SOURCES["kicad"]
        path = src.root / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
    else:
        src = SOURCES[key]
        path = src.root / rest
    if not path.is_file():
        raise FileNotFoundError(f"footprint {ref} -> {path}")
    return Resolved(path, src, _rel(src, path))


def footprint_lib_id(ref: str, res: Resolved) -> str:
    if ref.startswith("kicad:"):
        return ref.removeprefix("kicad:")
    return f"{res.path.parent.stem}:{res.path.stem}"


def resolve_symbol(ref: str) -> tuple[Resolved, str]:
    key, _, rest = ref.partition(":")
    if key == "kicad":
        lib, _, name = rest.partition(":")
        src = SOURCES["kicad"]
        path = src.root / "symbols" / f"{lib}.kicad_sym"
    else:
        src = SOURCES[key]
        file, _, name = rest.partition("#")
        path = src.root / file
    if not path.is_file():
        raise FileNotFoundError(f"symbol {ref} -> {path}")
    return Resolved(path, src, _rel(src, path)), name


_VAR = re.compile(r"^\$\{([A-Z0-9_]+)\}/(.*)$")
_STEP_EXTS = (".step", ".stp", ".STEP", ".STP")


def _prefer_step(path: Path) -> Path | None:
    for ext in _STEP_EXTS:
        cand = path.with_suffix(ext)
        if cand.is_file():
            return cand
    return path if path.is_file() else None


def resolve_model(model_path: str, footprint_file: Path | None) -> Resolved | None:
    """Map a KiCad model path (with ${VAR}s) to a local file, preferring STEP."""
    m = _VAR.match(model_path)
    cand: Path | None = None
    src: Source | None = None
    kbd = re.match(
        r"^(?:\$\{(?:KICAD_KBD_DIR|KBD_DIR)\}/|:KICAD_KBD_DIR:|\$\{KIPRJMOD\}/(?:kbd/)?)"
        r"(kicad-packages3D/.*)$",
        model_path,
    )
    if kbd:
        src = SOURCES["kbd"]
        cand = src.root / kbd.group(1)
    elif m:
        var, rest = m.groups()
        if re.fullmatch(r"KICAD\d*_3DMODEL_DIR", var):
            src = SOURCES["kicad3d"]
            cand = src.root / rest
        elif re.fullmatch(r"KICAD\d*_3RD_PARTY", var):
            parts = rest.split("/", 2)  # 3dmodels/<pkg>/<file...>
            if len(parts) == 3 and parts[1] == "com_github_ebastler_marbastlib":
                src = SOURCES["marbastlib"]
                cand = src.root / "3dmodels" / parts[2]
            elif len(parts) == 3 and parts[1] == "com_github_perigoso_keyswitch-kicad-library":
                src = SOURCES["kiswitch"]
                cand = src.root / "library/3dmodels" / parts[2]
    elif footprint_file is not None and not model_path.startswith("$"):
        p = Path(model_path)
        cand = p if p.is_absolute() else (footprint_file.parent / p).resolve()
        for s in SOURCES.values():
            if cand.is_relative_to(s.root):
                src = s
                break
    if cand is None or src is None:
        return None
    found = _prefer_step(cand)
    if found is None:
        return None
    return Resolved(found, src, _rel(src, found))
