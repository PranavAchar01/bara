"""A part fetched mid-build lands in the data tree the engine serves (BARA_DATA_DIR), so its
3D model is found on the next request instead of the part being drawn as a box."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = """
import json
from catalog_build import fetch_lcsc
from bara import kicad_generated
from bara.board import libs
from bara.live import fetch
paths = [fetch.FETCHED_JSONL, fetch_lcsc.FETCHED_JSONL, fetch_lcsc.ASSET_DIR,
         kicad_generated.DEFAULT_PATH, kicad_generated.GLB_DIR, libs.FETCHED_SRC]
print(json.dumps([str(p) for p in paths]))
"""


def test_fetch_and_index_paths_follow_the_data_dir(tmp_path: Path) -> None:
    env = {"BARA_DATA_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}
    out = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    paths = json.loads(out.stdout)
    assert all(p.startswith(str(tmp_path)) for p in paths), paths
