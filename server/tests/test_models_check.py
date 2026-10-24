"""render.models: parts the viewer can only draw as a box are named, mounting holes are not."""

from __future__ import annotations

from types import SimpleNamespace

from bara.live.runner import LiveRunner


def _part(name: str, kind: str, url: str | None, status: str = "ready") -> dict:
    assets = [{"kind": "glb", "role": "model", "url": url, "status": status}] if url else []
    return {"part_id": name, "card": {"display_name": name, "kind": kind, "assets": assets}}


def test_models_check_names_boxes_only() -> None:
    run = SimpleNamespace(
        state={
            "parts": [
                _part("Lazy KiCad", "component", "/assets/parts/kicad_gen/x.glb", "lazy"),
                _part("Never made", "component", "/assets/parts/no_such_file.glb", "missing"),
                _part("No file", "component", "/assets/parts/no_such_file_2.glb"),
                _part("No asset", "component", None),
                _part("Mounting hole M2", "fastener", None),
            ]
        }
    )
    check = LiveRunner._models_check(run)  # type: ignore[arg-type]
    assert check["status"] == "fail" and check["severity"] == "warning"
    assert check["message"] == "No 3D model, drawn as a box: Never made, No file, No asset"
    run.state["parts"] = run.state["parts"][:1]
    assert LiveRunner._models_check(run)["status"] == "pass"  # type: ignore[arg-type]
