"""The simulator routes: start, press, run tests, chat change that rebuilds the firmware."""

from __future__ import annotations

import shutil
import time

import pytest
from conftest import make_client
from test_firmware_sim_engine import joystick_handheld, part

from bara.firmware_sim.agent import rule_patch
from bara.firmware_sim.io import plan_io
from bara.firmware_sim.spice import run_all

needs_cc = pytest.mark.skipif(shutil.which("cc") is None, reason="no host C compiler")


def test_rule_patch_reads_common_asks() -> None:
    cfg = {"blink_ms": 500, "debounce_ms": 5, "tone_ms": 40}
    io = {"inputs": [{"id": "u_btn#0", "label": "A button"}]}
    assert rule_patch("make the LED blink faster", cfg, io) == {"blink_ms": 250}
    assert rule_patch("blink every 120 ms", cfg, io) == {"blink_ms": 120}
    assert rule_patch("debounce 12 ms please", cfg, io) == {"debounce_ms": 12}
    assert rule_patch("rename A button to Fire", cfg, io) == {"labels": {"u_btn#0": "Fire"}}
    assert rule_patch("hello", cfg, io) == {}


def test_spice_checks_report_numbers() -> None:
    state = joystick_handheld()
    state["parts"] += [
        part("u_bat", "power.battery", "18650 holder", pid="bat:holder_18650"),
        part("u_chg", "power.charger", "Li-ion charger with power path"),
        part("u_ldo", "power.regulator", "3.3 V LDO regulator"),
    ]
    results = run_all(plan_io(state), 5)
    if all(r["status"] == "unavailable" for r in results):
        pytest.skip("ngspice not installed")
    assert {r["id"] for r in results} >= {"spice.rail", "spice.debounce"}
    for r in results:
        assert r["group"] == "ngspice"
        assert r["status"] in ("pass", "skip", "warn"), (r["id"], r["summary"])
        if r["status"] == "pass":
            assert r["numbers"], r


@needs_cc
def test_sim_routes_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    with make_client(monkeypatch) as c:
        bid = c.post("/v1/builds", json={"prompt": "a small macropad with a knob"}).json()[
            "build_id"
        ]
        deadline = time.time() + 60
        while time.time() < deadline:
            st = c.get(f"/v1/builds/{bid}").json()
            if (st.get("build") or st).get("status") in ("done", "failed"):
                break
            time.sleep(0.2)
        r = c.post(f"/v1/builds/{bid}/sim/start", json={"labels": False})
        if r.status_code == 404:
            pytest.skip("mock build has no controller")
        assert r.status_code == 200, r.text
        sim = r.json()["sim"]
        assert sim["firmware"]["status"] == "ok", sim["firmware"]
        first = next(i for i in sim["io"]["inputs"] if i["kind"] in ("key", "button", "mkey"))
        seq = sim["snapshot"]["seq"]
        snap = c.post(
            f"/v1/builds/{bid}/sim/input", json={"id": first["id"], "action": "press", "since": seq}
        ).json()["snapshot"]
        assert any("press" in e.get("text", "") for e in snap["events"] if e["type"] == "serial")
        res = c.post(f"/v1/builds/{bid}/sim/tests", json={"ids": ["build.target", "emu.boot"]})
        assert [t["status"] for t in res.json()["results"]] == ["pass", "pass"]
        chat = c.post(f"/v1/builds/{bid}/sim/chat", json={"message": "blink every 200 ms"})
        reply = chat.json()["reply"]
        assert reply["rebuilt"] and reply["changes"]["blink_ms"] == 200
        assert chat.json()["sim"]["config"]["blink_ms"] == 200
        assert c.get(f"/v1/builds/{bid}/sim/source/bara_app.c").status_code == 200
        assert c.get(f"/v1/builds/{bid}/sim/source/..%2F..%2Fbuild.json").status_code == 404
