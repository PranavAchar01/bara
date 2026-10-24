"""Upstream sources for every footprint, symbol and 3D model in the catalog.

Each entry records where the files live on this machine, the public URL, the pinned
commit or release, and the licence exactly as the upstream states it. The paths are
outside the repo (shallow clones under ~/helloworld/bara-sources, plus the KiCad
install); nothing upstream is copied into the repo except the converted GLBs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

KICAD_SHARE = Path(
    os.environ.get("KICAD_SHARE", "/Applications/KiCad/KiCad.app/Contents/SharedSupport")
)
SOURCES_ROOT = Path(os.environ.get("BARA_SOURCES", str(Path.home() / "helloworld/bara-sources")))


@dataclass(frozen=True)
class Licence:
    spdx: str
    name: str
    url: str | None
    commercial_ok: str  # yes | no | unknown
    copyleft: str
    attribution_required: str
    notes: str | None = None

    def as_record(self) -> dict[str, object]:
        rec: dict[str, object] = {
            "spdx": self.spdx,
            "name": self.name,
            "url": self.url,
            "commercial_ok": self.commercial_ok,
            "copyleft": self.copyleft,
            "attribution_required": self.attribution_required,
        }
        if self.notes:
            rec["notes"] = self.notes
        return rec


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    root: Path
    url: str
    commit: str
    licence: Licence
    route: str

    def file_url(self, rel: str) -> str:
        """Public URL of one file at the pinned commit (best effort for KiCad)."""
        if self.url.startswith("https://github.com/"):
            return f"{self.url}/blob/{self.commit}/{rel}"
        return f"{self.url}/-/blob/{self.commit}/{rel}"


KICAD_LICENCE = Licence(
    spdx="CC-BY-SA-4.0",
    name="CC-BY-SA 4.0 with the KiCad library exception",
    url="https://www.kicad.org/libraries/license/",
    commercial_ok="yes",
    copyleft="yes",
    attribution_required="no",
    notes=(
        "KiCad library exception: using the symbols, footprints and 3D models in a "
        "design does not make the design subject to the licence."
    ),
)

VENDOR_MODEL_LICENCE = Licence(
    spdx="NOASSERTION",
    name="Third-party vendor model redistributed by marbastlib",
    url="https://github.com/ebastler/marbastlib#3d-models",
    commercial_ok="unknown",
    copyleft="unknown",
    attribution_required="unknown",
    notes=(
        "marbastlib README: these models were provided by someone else and are NOT "
        "covered by the repository licence."
    ),
)

SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        Source(
            key="kicad",
            title="KiCad official libraries 10.0.7 (symbols, footprints, packages3D)",
            root=KICAD_SHARE,
            url="https://gitlab.com/kicad/libraries/kicad-footprints",
            commit="10.0.7",
            licence=KICAD_LICENCE,
            route="kicad_library",
        ),
        Source(
            key="kicad3d",
            title="KiCad official 3D models 10.0.7",
            root=KICAD_SHARE / "3dmodels",
            url="https://gitlab.com/kicad/libraries/kicad-packages3D",
            commit="10.0.7",
            licence=KICAD_LICENCE,
            route="kicad_library",
        ),
        Source(
            key="kiswitch",
            title="kiswitch keyswitch KiCad library",
            root=SOURCES_ROOT / "kiswitch",
            url="https://github.com/kiswitch/kiswitch",
            commit="aefcf65038d48d2666ff14530d482be3c350fa6e",
            licence=Licence(
                spdx="MIT OR CC-BY-SA-4.0",
                name="MIT or CC-BY-SA 4.0 (dual licensed)",
                url="https://github.com/kiswitch/kiswitch#license",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="yes",
                notes="Dual licensed; MIT chosen here, keep the copyright notice.",
            ),
            route="kicad_3rd_party",
        ),
        Source(
            key="marbastlib",
            title="marbastlib keyboard KiCad library",
            root=SOURCES_ROOT / "marbastlib",
            url="https://github.com/ebastler/marbastlib",
            commit="6b0a9a73f579e377816d60b58eac2b3252de7868",
            licence=Licence(
                spdx="CERN-OHL-P-2.0",
                name="CERN Open Hardware Licence v2 Permissive",
                url="https://github.com/ebastler/marbastlib/blob/main/LICENSE",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="yes",
            ),
            route="kicad_3rd_party",
        ),
        Source(
            key="seeed_opl",
            title="Seeed Studio OPL KiCad library",
            root=SOURCES_ROOT / "OPL_Kicad_Library",
            url="https://github.com/Seeed-Studio/OPL_Kicad_Library",
            commit="b0035c51eb0348bb3e165fdb2f2765fa3d1d17bd",
            licence=Licence(
                spdx="CC-BY-SA-4.0",
                name="CC-BY-SA 4.0",
                url="https://github.com/Seeed-Studio/OPL_Kicad_Library/blob/master/LICENSE",
                commercial_ok="yes",
                copyleft="yes",
                attribution_required="yes",
            ),
            route="kicad_3rd_party",
        ),
        Source(
            key="pmw3360_breakout",
            title="jfedor2 PMW3360 breakout (KiCad footprint + STEP)",
            root=SOURCES_ROOT / "pmw3360-breakout",
            url="https://github.com/jfedor2/pmw3360-breakout",
            commit="13738eece595fefb1246524429a3c1d3ba7e6ebf",
            licence=Licence(
                spdx="CC0-1.0",
                name="CC0 1.0 Universal",
                url="https://github.com/jfedor2/pmw3360-breakout/blob/master/LICENSE",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="no",
            ),
            route="kicad_3rd_party",
        ),
        Source(
            key="klp",
            title="KLP Lame keycaps (STEP)",
            root=SOURCES_ROOT / "KLP-Lame-Keycaps",
            url="https://github.com/braindefender/KLP-Lame-Keycaps",
            commit="8e4b89b484cafe3bcaced6b459a4e29660991a40",
            licence=Licence(
                spdx="CC-BY-SA-4.0",
                name="CC-BY-SA 4.0",
                url="https://github.com/braindefender/KLP-Lame-Keycaps",
                commercial_ok="yes",
                copyleft="yes",
                attribution_required="yes",
                notes="Attribution: KLP Lame Keycaps by braindefender.",
            ),
            route="open_model",
        ),
        Source(
            key="dsa",
            title="anhthang DSA keycap models (STEP)",
            root=SOURCES_ROOT / "downloads/dsa-keycap",
            url="https://github.com/anhthang/dsa-keycap",
            commit="efc08d0a025057ede925347e8b07d85971778f2b",
            licence=Licence(
                spdx="MIT",
                name="MIT",
                url="https://github.com/anhthang/dsa-keycap",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="yes",
            ),
            route="open_model",
        ),
        Source(
            key="knobby",
            title="quadule knobby knob (STEP)",
            root=SOURCES_ROOT / "downloads/knobby",
            url="https://github.com/quadule/knobby",
            commit="e2f72c0cf8843eea389f30b917bd3db0cc113ffd",
            licence=Licence(
                spdx="MIT",
                name="MIT",
                url="https://github.com/quadule/knobby",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="yes",
            ),
            route="open_model",
        ),
        Source(
            key="flactyl",
            title="yangit flactyl shared 3D models (nice!nano STEP)",
            root=SOURCES_ROOT / "downloads/flactyl",
            url="https://github.com/yangit/flactyl",
            commit="e927717dd869d145414e8439c2a5687b8927abc3",
            licence=Licence(
                spdx="MIT",
                name="MIT",
                url="https://github.com/yangit/flactyl",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="yes",
            ),
            route="open_model",
        ),
        Source(
            key="crkbd",
            title="foostan crkbd (Corne) KiCad boards",
            root=SOURCES_ROOT / "crkbd",
            url="https://github.com/foostan/crkbd",
            commit="63366fb7f51cf2a796462fdd90527e99dd126055",
            licence=Licence(
                spdx="MIT",
                name="MIT (repo also ships CC-BY-4.0)",
                url="https://github.com/foostan/crkbd",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="yes",
            ),
            route="design_import",
        ),
        Source(
            key="kbd",
            title="foostan kbd KiCad library (inside the crkbd repo)",
            root=SOURCES_ROOT / "crkbd/pcbs/common/kbd",
            url="https://github.com/foostan/crkbd",
            commit="63366fb7f51cf2a796462fdd90527e99dd126055",
            licence=Licence(
                spdx="MIT",
                name="MIT (Copyright (c) 2020 foostan)",
                url="https://github.com/foostan/crkbd/blob/main/pcbs/common/kbd/LICENSE",
                commercial_ok="yes",
                copyleft="no",
                attribution_required="yes",
            ),
            route="kicad_3rd_party",
        ),
    ]
}

# Upstream paths of the files fetched individually (not whole clones).
DOWNLOAD_PATHS = {
    "dsa": "",
    "knobby": "case/",
    "flactyl": "scad/5.0/shared-3d-models/",
    "kbd": "pcbs/common/kbd/",
}


def source_rel_url(src: Source, rel: str) -> str:
    """Public URL of a file given its path relative to the local source root."""
    if src.key == "kicad":
        lib = rel.split("/")[1] if rel.startswith(("footprints/", "symbols/")) else rel
        if rel.startswith("footprints/"):
            return (
                "https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/"
                f"{src.commit}/{rel.removeprefix('footprints/')}"
            )
        if rel.startswith("symbols/"):
            return (
                "https://gitlab.com/kicad/libraries/kicad-symbols/-/blob/"
                f"{src.commit}/{rel.removeprefix('symbols/')}"
            )
        return f"https://gitlab.com/kicad/libraries/kicad-footprints/-/tree/{src.commit}/{lib}"
    if src.key == "kicad3d":
        return f"{src.url}/-/blob/{src.commit}/{rel}"
    return src.file_url(DOWNLOAD_PATHS.get(src.key, "") + rel)
