"""ngspice through ctypes.

KiCad ships ngspice only as a shared library (no `ngspice` binary, no simulate command in
kicad-cli), so this drives libngspice directly: ngSpice_Init, ngSpice_Circ, ngSpice_Command and
ngGet_Vec_Info. If the bundled library is missing, a Homebrew libngspice or `ngspice` binary
(batch mode, ASCII rawfile) is used when installed. Nothing is ever installed from here.
"""

from __future__ import annotations

import ctypes as C
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

KICAD_APP = Path("/Applications/KiCad/KiCad.app/Contents")
LIB_CANDIDATES = [
    KICAD_APP / "PlugIns/sim/libngspice.0.dylib",
    KICAD_APP / "Frameworks/libngspice.0.dylib",
    Path("/opt/homebrew/lib/libngspice.dylib"),
    Path("/usr/local/lib/libngspice.dylib"),
    Path("/usr/lib/x86_64-linux-gnu/libngspice.so.0"),
]

_SEND = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
_STAT = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
_EXIT = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)


class _VecInfo(C.Structure):
    _fields_ = [
        ("name", C.c_char_p),
        ("type", C.c_int),
        ("flags", C.c_short),
        ("real", C.POINTER(C.c_double)),
        ("comp", C.c_void_p),
        ("length", C.c_int),
    ]


class SimError(RuntimeError):
    pass


Result = dict[str, list[float]]


class Ngspice:
    """One process-wide libngspice instance (the library has global state, so calls are locked)."""

    _lock = threading.Lock()

    def __init__(self, lib_path: Path | None = None) -> None:
        path = lib_path or next((p for p in LIB_CANDIDATES if p.exists()), None)
        if path is None:
            raise SimError("libngspice not found")
        self.path = path
        self._lib = C.CDLL(str(path))
        self._lib.ngGet_Vec_Info.restype = C.POINTER(_VecInfo)
        self._lib.ngSpice_AllVecs.restype = C.POINTER(C.c_char_p)
        self._lib.ngSpice_CurPlot.restype = C.c_char_p
        self.log: list[str] = []
        self._send = _SEND(self._on_send)
        self._stat = _STAT(lambda _m, _i, _u: 0)
        self._exit = _EXIT(lambda _a, _b, _c, _d, _e: 0)
        rc = self._lib.ngSpice_Init(
            self._send, self._stat, self._exit, None, None, C.c_bool(False), None
        )
        if rc != 0:
            raise SimError(f"ngSpice_Init returned {rc}")

    def _on_send(self, msg: bytes, _ident: int, _user: int) -> int:
        self.log.append(msg.decode(errors="replace"))
        return 0

    def _command(self, cmd: str) -> None:
        rc = self._lib.ngSpice_Command(cmd.encode())
        if rc != 0:
            raise SimError(f"ngspice command {cmd!r} failed: {self._errors()}")

    def _errors(self) -> str:
        bad = [m for m in self.log if "rror" in m or "fatal" in m.lower()]
        return "; ".join(bad[-3:]) or "no message"

    def _vectors(self, plot: str) -> Result:
        out: Result = {}
        names = self._lib.ngSpice_AllVecs(plot.encode())
        i = 0
        while names and names[i]:
            name = names[i].decode()
            info = self._lib.ngGet_Vec_Info(f"{plot}.{name}".encode())
            if info and info.contents.real:
                n = info.contents.length
                out[name.lower()] = [info.contents.real[k] for k in range(n)]
            i += 1
        return out

    def run(self, deck: list[str], analyses: list[str]) -> list[Result]:
        """Load `deck` (title line first, no .end, no analysis cards) and run each analysis
        command ("op", "tran 1u 4m"). Returns one {vector: values} dict per analysis."""
        with self._lock:
            self.log.clear()
            self._command("remcirc")
            lines = [*deck, ".end"]
            arr = (C.c_char_p * (len(lines) + 1))(*[ln.encode() for ln in lines], None)
            if self._lib.ngSpice_Circ(arr) != 0:
                raise SimError(f"deck rejected: {self._errors()}")
            results = []
            for cmd in analyses:
                self._command(cmd)
                plot = (self._lib.ngSpice_CurPlot() or b"").decode()
                if not plot or plot == "const":
                    raise SimError(f"{cmd!r} produced no plot: {self._errors()}")
                results.append(self._vectors(plot))
            return results


_instance: Ngspice | None = None


def get_engine() -> Ngspice:
    global _instance
    if _instance is None:
        try:
            _instance = Ngspice()
        except (SimError, OSError):
            if shutil.which("ngspice") is None:
                raise
            return _BinaryEngine()  # type: ignore[return-value]
    return _instance


def parse_ascii_raw(text: str) -> Result:
    """Parse an ngspice ASCII rawfile (single plot) into {vector: values}."""
    names: list[str] = []
    cols: list[list[float]] = []
    lines = iter(text.splitlines())
    n_vars = n_pts = 0
    for ln in lines:
        if ln.startswith("No. Variables:"):
            n_vars = int(ln.split(":")[1])
        elif ln.startswith("No. Points:"):
            n_pts = int(ln.split(":")[1])
        elif ln.startswith("Variables:"):
            for _ in range(n_vars):
                parts = next(lines).split()
                names.append(parts[1].lower())
            cols = [[] for _ in range(n_vars)]
        elif ln.startswith("Values:"):
            break
    for _ in range(n_pts):
        for k in range(n_vars):
            tok = next(lines).split()
            cols[k].append(float(tok[-1]))
    return dict(zip(names, cols, strict=True))


class _BinaryEngine:
    """Fallback: a Homebrew `ngspice` binary in batch mode, results through ASCII rawfiles."""

    path = Path(shutil.which("ngspice") or "ngspice")

    def run(self, deck: list[str], analyses: list[str]) -> list[Result]:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctl = [".control", "set filetype=ascii"]
            for i, cmd in enumerate(analyses):
                ctl += [cmd, f"write {tmp / f'p{i}.raw'} all"]
            ctl += [".endc"]
            (tmp / "deck.cir").write_text("\n".join([*deck, *ctl, ".end"]) + "\n")
            proc = subprocess.run(
                [str(self.path), "-b", str(tmp / "deck.cir")],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            out = []
            for i in range(len(analyses)):
                raw = tmp / f"p{i}.raw"
                if not raw.exists():
                    tail = proc.stderr[-200:] or proc.stdout[-200:]
                    raise SimError(f"ngspice binary failed: {tail}")
                out.append(parse_ascii_raw(raw.read_text()))
            return out
