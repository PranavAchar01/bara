"""A cached LCSC part is offered only as the stock KiCad library part it names, never itself."""

from __future__ import annotations

from typing import Any

from bara.live.catalog_source import WithFetched

LCSC = {
    "part_id": "lcsc:drv8833pwpr_c50506",
    "mpn": "DRV8833PWPR",
    "functions": [{"function_id": "component.ic", "primary": True}],
    "interfaces": [],
}
OTHER = {
    "part_id": "lcsc:bmi270_c2836813",
    "mpn": "BMI270",
    "functions": [{"function_id": "sense.imu", "primary": True}],
    "interfaces": [{"type": "i2c"}],
}
STOCK = {
    "part_id": "kicadgen:kicad:sym:Driver_Motor:DRV8833PWP",
    "name": "DRV8833PWP",
    "fp_ok": True,
    "functions": [{"function_id": "component.driver", "primary": True}],
    "interfaces": [],
}


class _Base:
    name = "catalog_db"

    def query(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return []

    def get_part(self, part_id: str) -> dict[str, Any]:
        raise KeyError(part_id)


def _search(text: str, kind: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    return [STOCK] if text.upper() == "DRV8833PWP" else []


def test_the_library_part_takes_the_fetched_role() -> None:
    src = WithFetched(_Base(), [LCSC, OTHER], _search)
    ics = src.query(function="component.ic")
    assert [p["part_id"] for p in ics] == [STOCK["part_id"]]
    assert ics[0]["replaces"] == [LCSC["part_id"]]
    assert ics[0]["functions"][0] == {"function_id": "component.ic", "primary": True}
    # a part the library lacks is never offered: vendor downloads are not open source
    assert src.query(function="sense.imu") == []
    # a build that chose the LCSC row can still read it
    assert src.get_part(LCSC["part_id"])["mpn"] == "DRV8833PWPR"


def test_without_the_library_no_fetched_part_is_served() -> None:
    src = WithFetched(_Base(), [LCSC, OTHER])
    assert src.query(function="component.ic") == []


def test_two_reels_of_one_chip_keep_both_roles() -> None:
    reel = {**LCSC, "part_id": "lcsc:drv8833pwr_c1", "mpn": "DRV8833PWPT"}
    reel["functions"] = [{"function_id": "output.haptic", "primary": True}]
    src = WithFetched(_Base(), [LCSC, reel], lambda text, **k: [STOCK] if "DRV8833" in text else [])
    for fid in ("component.ic", "output.haptic"):
        assert [p["part_id"] for p in src.query(function=fid)] == [STOCK["part_id"]]


def test_a_vendor_download_is_not_open_source() -> None:
    from bara.live.compose import open_source

    assert not open_source(LCSC)
    assert open_source(STOCK)
