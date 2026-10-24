"""Find design names the open KiCad project closest to the request, or says there is none."""

from __future__ import annotations

from bara.live import open_designs


def test_a_named_device_finds_its_open_design() -> None:
    device, cands = open_designs.closest("a game boy")
    assert device == "game boy" and cands
    assert open_designs.closest("a 60 gram wireless gaming mouse")[0] == "wireless gaming mouse"
    rows = open_designs.rows("an mp3 player")
    assert rows and rows[0]["score"] == 1.0 and rows[0]["design_id"].startswith("https://")


def test_an_unlisted_device_finds_nothing() -> None:
    assert open_designs.closest("a 60% mechanical keyboard") == ("", [])
