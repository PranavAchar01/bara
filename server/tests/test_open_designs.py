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


def test_search_uses_github_repo_search_without_a_web_key(monkeypatch, tmp_path):
    import asyncio

    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/search/repositories":
            assert "kicad" in req.url.params["q"]
            return httpx.Response(200, json={"items": [{"full_name": "maker/handheld"}]})
        if req.url.path == "/repos/maker/handheld":
            return httpx.Response(200, json={"default_branch": "main", "stargazers_count": 7})
        tree = [{"path": "pcb/handheld.kicad_pcb"}, {"path": "case/top.stl"}]
        return httpx.Response(200, json={"tree": tree})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        open_designs.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(open_designs, "SEARCH_CACHE", tmp_path)
    monkeypatch.delenv("YOU_API_KEY", raising=False)
    cands, note = asyncio.run(open_designs.search("a handheld console"))
    assert note == "ok"
    assert cands[0]["repo"] == "https://github.com/maker/handheld"
    assert cands[0]["fit"] == "close"
