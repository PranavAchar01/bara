"""Builds on one board become one combined device with one plain title."""

from __future__ import annotations

import asyncio

from bara.scenes import Scenes, combined_title, detect_pairs, device_noun, joined_title


def test_device_noun_reads_the_device() -> None:
    assert device_noun("4-key USB macropad for streaming controls") == "macropad"
    assert device_noun("small desktop status display panel") == "desktop display"
    assert device_noun("a wireless mouse that pairs over Bluetooth with a keyboard") == "mouse"


def test_joined_title_is_one_plain_sentence() -> None:
    names = ["4-key USB macropad for streaming controls", "small desktop status display panel"]
    assert joined_title(names) == "Macropad with desktop display"
    assert joined_title(["keyboard", "mouse", "wrist rest"]) == "Keyboard with mouse and wrist rest"
    assert joined_title(["keyboard", "keyboard"]) == "Keyboard"


def test_short_join_needs_no_model() -> None:
    title, by = asyncio.run(combined_title(["low-profile keyboard", "wireless mouse"]))
    assert (title, by) == ("Keyboard with mouse", "rules")


def test_put_merges_and_annotates(tmp_path) -> None:
    s = Scenes(tmp_path / "scenes.json")
    a = s.put(["b_a", "b_b"], "Macropad with desktop display", "rules")
    assert s.of("b_b")["scene_id"] == a["scene_id"]
    merged = s.put(["b_b", "b_c"], "Three", "rules")
    assert merged["builds"] == ["b_b", "b_c", "b_a"]
    assert len(s.all()) == 1
    rows = s.annotate([{"build_id": "b_a"}, {"build_id": "b_z"}])
    assert rows[0]["scene"]["title"] == "Three"
    assert "scene" not in rows[1]


def _row(build_id: str, prompt: str, at: str) -> dict[str, str]:
    return {"build_id": build_id, "prompt": prompt, "created_at": f"2026-10-25T{at}Z"}


def test_detect_pairs_finds_the_companion_just_after() -> None:
    rows = [
        _row("b_m", "create a stream deck with 4 buttons", "05:59:00"),
        _row("b_d", "a desktop monitor that connects to a 4-button stream deck", "06:00:25"),
        _row("b_x", "a macropad with a knob", "06:10:00"),
    ]
    assert detect_pairs(rows) == [["b_m", "b_d"]]


def test_scene_routes_name_and_list(monkeypatch, tmp_path) -> None:
    from conftest import make_client

    with make_client(monkeypatch, BARA_DATA_DIR=str(tmp_path / "data")) as c:
        bad = c.post("/v1/scenes", json={"builds": ["b_only"]})
        assert bad.status_code == 400
        r = c.post(
            "/v1/scenes",
            json={
                "builds": ["b_aaaaaaaaaaaa", "b_bbbbbbbbbbbb"],
                "names": ["USB macropad with rotary knob", "kitchen countdown timer"],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["scene"]["title"] == "Macropad with kitchen countdown timer"
        listed = c.get("/v1/scenes").json()["scenes"][0]["builds"]
        assert listed == ["b_aaaaaaaaaaaa", "b_bbbbbbbbbbbb"]
        again = c.post(
            "/v1/scenes",
            json={"builds": ["b_aaaaaaaaaaaa", "b_bbbbbbbbbbbb"], "names": ["a", "b"]},
        )
        assert again.json()["scene"]["title"] == "Macropad with kitchen countdown timer"
