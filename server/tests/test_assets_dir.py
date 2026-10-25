"""Model lookups read the asset tree the server serves, wherever BARA_DATA_DIR puts it."""

import os
import subprocess
import sys
from pathlib import Path


def test_assets_dir_follows_bara_data_dir(tmp_path: Path) -> None:
    env = {**os.environ, "BARA_DATA_DIR": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "-c", "from bara.live.compose import ASSETS_DIR; print(ASSETS_DIR)"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(out.stdout.strip()) == tmp_path / "assets"
