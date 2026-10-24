"""Build the sculpted shell for every ProductForm fixture, with no model call.

    BARA_SHELL_OUT=/some/dir PYTHONPATH=server/src python scripts/build_shell_fixtures.py [name...]

Writes <name>.glb next to a short report of the engine's own checks.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

out = Path(os.environ.get("BARA_SHELL_OUT", "shell-out"))
out.mkdir(parents=True, exist_ok=True)
data = Path(tempfile.mkdtemp(prefix="bara-shell-"))
os.environ["BARA_DATA_DIR"] = str(data)

from bara.geometry import enclose_report
from bara.geometry.shell_fixtures import FIXTURES, brief_for


def main(names: list[str]) -> int:
    bad = 0
    for name in names or list(FIXTURES):
        fx = FIXTURES[name]()
        t0 = time.perf_counter()
        rep = enclose_report(fx["board"], [], brief_for(fx))
        dt = time.perf_counter() - t0
        glb = next(a for a in rep.enclosure["assets"] if a["kind"] == "glb")
        shutil.copy(data / "assets" / glb["url"][len("/assets/") :], out / f"{name}.glb")
        failed = [c for c in rep.checks if c["status"] != "pass"]
        bad += len(failed)
        print(f"{name}: {dt:.1f}s, {len(rep.checks)} checks, {len(failed)} not passing")
        for c in failed:
            print(f"   {c['rule_id']} {c['status']}: {c['message']}")
    shutil.rmtree(data, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
