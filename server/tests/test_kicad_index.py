"""Generated tier: parse fixtures, join symbol -> footprint -> 3D, FTS search, ranking."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bara import kicad_generated  # noqa: E402
from bara.live.catalog_source import WithGenerated  # noqa: E402
from catalog_build import kicad_index as ki  # noqa: E402

SYM = """(kicad_symbol_lib
\t(version 20251024)
\t(generator "kicad_symbol_editor")
\t(symbol "ADNS-TEST"
\t\t(property "Reference" "U" (at 0 0 0))
\t\t(property "Value" "ADNS-TEST" (at 0 0 0))
\t\t(property "Footprint" "Pkg_Test:SOIC-4" (at 0 0 0))
\t\t(property "Datasheet" "https://example.com/adns.pdf" (at 0 0 0))
\t\t(property "Description" "Optical mouse sensor, \\"laser\\" tracking" (at 0 0 0))
\t\t(property "ki_keywords" "mouse optical navigation" (at 0 0 0))
\t\t(symbol "ADNS-TEST_1_1"
\t\t\t(pin input line (at 0 0 0) (length 2)
\t\t\t\t(name "MOSI" (effects (font (size 1 1))))
\t\t\t\t(number "1" (effects (font (size 1 1))))
\t\t\t)
\t\t\t(pin input line (at 0 0 0) (length 2)
\t\t\t\t(name "SCLK" (effects (font (size 1 1))))
\t\t\t\t(number "2" (effects (font (size 1 1))))
\t\t\t)
\t\t)
\t\t(symbol "ADNS-TEST_2_1"
\t\t\t(pin input line (at 0 0 0) (length 2)
\t\t\t\t(name "MOSI" (effects (font (size 1 1))))
\t\t\t\t(number "1" (effects (font (size 1 1))))
\t\t\t)
\t\t)
\t)
\t(symbol "ADNS-CHILD"
\t\t(extends "ADNS-TEST")
\t\t(property "Description" "Child variant" (at 0 0 0))
\t)
\t(symbol "Lonely"
\t\t(property "Footprint" "" (at 0 0 0))
\t\t(property "Description" "No footprint" (at 0 0 0))
\t)
)
"""

MOD = """(footprint "SOIC-4"
\t(version 20260206)
\t(descr "4 pin small outline")
\t(tags "soic sensor")
\t(attr smd)
\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
\t(pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu"))
\t(pad "" smd rect (at 2 0) (size 1 1) (layers "F.Cu"))
\t(model "${KICAD10_3DMODEL_DIR}/Pkg_Test.3dshapes/SOIC-4.wrl"
\t\t(offset (xyz 0 0 0))
\t)
)
"""


@pytest.fixture
def lib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    share = tmp_path / "share"
    (share / "symbols").mkdir(parents=True)
    (share / "symbols" / "Sensor_Test.kicad_sym").write_text(SYM)
    pretty = share / "footprints" / "Pkg_Test.pretty"
    pretty.mkdir(parents=True)
    (pretty / "SOIC-4.kicad_mod").write_text(MOD)
    (pretty / "Orphan.kicad_mod").write_text(MOD.replace("SOIC-4", "Orphan"))
    shapes = share / "3dmodels" / "Pkg_Test.3dshapes"
    shapes.mkdir(parents=True)
    (shapes / "SOIC-4.step").write_text("ISO-10303-21;")
    fake = {
        "kicad": SimpleNamespace(root=share, commit="test", licence=None),
        "kicad3d": SimpleNamespace(root=share / "3dmodels", commit="test", licence=None),
    }
    monkeypatch.setattr(ki, "SOURCES", fake)
    monkeypatch.setattr(ki, "INDEXED", ("kicad",))
    monkeypatch.setattr(ki, "CATALOG", tmp_path)
    monkeypatch.setattr(ki, "INDEX_JSONL", tmp_path / "kicad_index.jsonl")
    monkeypatch.setattr(ki, "INDEX_SQLITE", tmp_path / "kicad_index.sqlite")
    return share


def test_parse_symbol_lib_pins_extends_and_escapes() -> None:
    syms = {s["name"]: s for s in ki.parse_symbol_lib(SYM)}
    assert set(syms) == {"ADNS-TEST", "ADNS-CHILD", "Lonely"}
    base = syms["ADNS-TEST"]
    assert base["pins"] == 2  # unique pin numbers across units
    assert base["props"]["Description"] == 'Optical mouse sensor, "laser" tracking'
    assert base["pin_names"] == ["MOSI", "SCLK"]
    child = syms["ADNS-CHILD"]
    assert child["pins"] == 2 and child["props"]["Footprint"] == "Pkg_Test:SOIC-4"
    assert child["props"]["Description"] == "Child variant"


def test_parse_footprint() -> None:
    info = ki.parse_footprint(MOD)
    assert info["pads"] == 2 and info["pad_total"] == 3  # the unnumbered pad is not counted
    assert info["mount"] == "smd" and info["descr"] == "4 pin small outline"
    assert info["models"] == ["${KICAD10_3DMODEL_DIR}/Pkg_Test.3dshapes/SOIC-4.wrl"]


def test_build_joins_symbol_footprint_model(lib: Path) -> None:
    rows, meta = ki.build_rows(("kicad",))
    assert meta["symbols"] == 3 and meta["footprints"] == 2
    assert meta["symbols_with_footprint"] == 2 and meta["symbols_with_3d"] == 2
    sym = next(r for r in rows if r.name == "ADNS-TEST")
    assert sym.footprint_part == "kicadgen:kicad:fp:Pkg_Test:SOIC-4"
    assert sym.model_source == "kicad3d"
    assert sym.model_path == "Pkg_Test.3dshapes/SOIC-4.step"  # .wrl reference resolved to STEP
    assert sym.pads == 2 and sym.mount == "smd"
    assert next(r for r in rows if r.name == "Lonely").footprint_part is None


def test_search_ranks_and_filters(lib: Path) -> None:
    rows, meta = ki.build_rows(("kicad",))
    ki.write_index(rows, meta)
    idx = kicad_generated.KicadIndex(ki.INDEX_SQLITE, glb_dir=lib / "glb")
    assert len(idx) == 5
    hits = idx.search("optical mouse sensor", kind="symbol")
    assert hits[0]["part_id"] == "kicadgen:kicad:sym:Sensor_Test:ADNS-TEST"
    assert hits[0]["tier"] == "kicad_generated"
    assert hits[0]["licence"]["name"] == "CC-BY-SA-4.0 WITH KiCad library exception"
    assert hits[0]["assets"][0]["url"] == "/assets/parts/kicad_gen/kicad_fp_Pkg_Test_SOIC-4.glb"
    assert [h["name"] for h in idx.search("mosi", kind="footprint")] == []  # pins are symbol-only
    assert idx.search("soic", kind="footprint")[0]["name"] in {"SOIC-4", "Orphan"}
    assert idx.search("zzzz nothing") == []
    assert idx.kicad(hits[0]["part_id"])["models"][0]["path"].endswith(
        "3dmodels/Pkg_Test.3dshapes/SOIC-4.step"
    )


def test_glb_is_lazy_and_cached(lib: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows, meta = ki.build_rows(("kicad",))
    ki.write_index(rows, meta)
    idx = kicad_generated.KicadIndex(ki.INDEX_SQLITE, glb_dir=lib / "glb")
    calls: list[str] = []

    def fake_convert(fp: dict, out: Path) -> bool:
        calls.append(fp["part_id"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"glTF")
        return True

    monkeypatch.setattr(kicad_generated, "_convert", fake_convert)
    pid = "kicadgen:kicad:sym:Sensor_Test:ADNS-TEST"
    assert not (lib / "glb").exists()  # nothing converted by indexing
    first = idx.ensure_glb(pid)
    second = idx.ensure_glb(pid)
    assert first == second and first is not None and first.is_file()
    assert calls == ["kicadgen:kicad:fp:Pkg_Test:SOIC-4"]  # converted once
    assert idx.ensure_glb("kicadgen:kicad:sym:Sensor_Test:Lonely") is None


def test_curated_ranks_above_generated(lib: Path) -> None:
    rows, meta = ki.build_rows(("kicad",))
    ki.write_index(rows, meta)
    idx = kicad_generated.KicadIndex(ki.INDEX_SQLITE, glb_dir=lib / "glb")
    curated = {"part_id": "mod:mouse_sensor", "display_name": "Mouse sensor"}

    class Base:
        name = "catalog_db"

        def search(self, text: str, limit: int = 20) -> list[dict]:
            return [curated]

        def get_part(self, part_id: str) -> dict:
            return curated

    src = WithGenerated(Base(), idx)
    ids = [p["part_id"] for p in src.search("optical mouse sensor")]
    assert ids[0] == "mod:mouse_sensor" and ids[1].startswith("kicadgen:")
    assert [p["part_id"] for p in src.search("optical mouse", kind="symbol")][0].startswith(
        "kicadgen:"
    )
    assert src.get_part("kicadgen:kicad:sym:Sensor_Test:ADNS-TEST")["name"] == "ADNS-TEST"
    assert src.get_part("mod:mouse_sensor") is curated


def test_package_sig_ignores_pad_and_thin_prefix() -> None:
    sig = kicad_generated.package_sig
    assert sig("VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm") == ("QFN", "16", "3x3", "0.5")
    assert sig("QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm") == ("QFN", "16", "3x3", "0.5")
    assert sig("HTSSOP-16-1EP_4.4x5mm_P0.65mm") == sig("TSSOP-16_4.4x5mm_P0.65mm")
    assert sig("QFN-16-1EP_4x4mm_P0.65mm") != sig("QFN-16-1EP_3x3mm_P0.5mm")
    assert sig("PinHeader_1x02_P2.54mm_Vertical") is None


def test_model_lent_by_same_package_sibling(lib: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pretty = lib / "footprints" / "Pkg_Test.pretty"
    shapes = lib / "3dmodels" / "Pkg_Test.3dshapes"
    lent = "QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm"
    for name in ("VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm", lent, "QFN-16-1EP_4x4mm_P0.65mm"):
        (pretty / f"{name}.kicad_mod").write_text(MOD.replace("SOIC-4", name))
    for name in (lent, "QFN-16-1EP_4x4mm_P0.65mm"):
        (shapes / f"{name}.step").write_text("ISO-10303-21;")
    rows, meta = ki.build_rows(("kicad",))
    ki.write_index(rows, meta)
    idx = kicad_generated.KicadIndex(ki.INDEX_SQLITE, glb_dir=lib / "glb")
    calls: list[str] = []

    def fake_convert(fp: dict, out: Path) -> bool:
        calls.append(fp["part_id"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"glTF")
        return True

    monkeypatch.setattr(kicad_generated, "_convert", fake_convert)
    pid = "kicadgen:kicad:fp:Pkg_Test:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm"
    lender = f"kicadgen:kicad:fp:Pkg_Test:{lent}"
    assert idx.model_footprint("Pkg_Test:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm") == lender
    asset = idx.get_part(pid)["assets"][0]
    assert asset["url"].endswith(f"{kicad_generated.glb_stem(lender)}.glb")
    assert idx.ensure_glb(pid) is not None and calls == [lender]
    assert idx.model_footprint("Pkg_Test:Orphan") is None  # no same-size sibling, no model


def test_name_alike_sibling_must_match_the_outline(
    lib: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from catalog_build import sources

    monkeypatch.setattr(sources, "SOURCES", {"kicad": SimpleNamespace(root=lib)})
    pretty = lib / "footprints" / "Pkg_Test.pretty"
    shapes = lib / "3dmodels" / "Pkg_Test.3dshapes"

    def mod(name: str, w: float) -> str:
        yard = f'\t(fp_rect (start 0 0) (end {w} {w}) (layer "F.CrtYd"))\n)\n'
        return MOD.replace("SOIC-4", name).rstrip().removesuffix(")") + yard

    (pretty / "Trim_3386P_Vertical.kicad_mod").write_text(mod("Trim_3386P_Vertical", 9.5))
    (pretty / "Trim_3339P_Vertical.kicad_mod").write_text(mod("Trim_3339P_Vertical", 7.0))
    (shapes / "Trim_3339P_Vertical.step").write_text("ISO-10303-21;")
    ki.write_index(*ki.build_rows(("kicad",)))
    idx = kicad_generated.KicadIndex(ki.INDEX_SQLITE, glb_dir=lib / "glb")
    assert idx.model_footprint("Pkg_Test:Trim_3386P_Vertical") is None  # 9.5 mm vs 7 mm body
    (pretty / "Trim_3386W_Vertical.kicad_mod").write_text(mod("Trim_3386W_Vertical", 9.0))
    (shapes / "Trim_3386W_Vertical.step").write_text("ISO-10303-21;")
    ki.write_index(*ki.build_rows(("kicad",)))
    idx = kicad_generated.KicadIndex(ki.INDEX_SQLITE, glb_dir=lib / "glb")
    assert idx.model_footprint("Pkg_Test:Trim_3386P_Vertical") == (
        "kicadgen:kicad:fp:Pkg_Test:Trim_3386W_Vertical"
    )
