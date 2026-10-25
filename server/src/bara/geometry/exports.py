"""Build exports: case STL / 3MF, BOM CSV, wiring CSV, KiCad project zip, board STEP.

Every file is read from an asset this server actually has. When a file does not exist the
export raises ExportError("E_ASSET_MISSING") instead of inventing one (mock builds reference
fixture URLs that are not on disk, so they keep answering E_ASSET_MISSING for stl/3mf/step).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from bara.config import load_settings
from bara.geometry.meshio import MeshPart, read_3mf, read_stl, write_3mf, write_stl

KICAD_SHARE = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport")
KICAD_FOOTPRINTS_URL = "https://gitlab.com/kicad/libraries/kicad-footprints"
KICAD_LIB_LICENCE = "CC-BY-SA-4.0"  # KiCad library licence (with the design exception)
STEP_TIMEOUT_S = 240

FORMATS = {"stl", "3mf", "bom_csv", "wiring_csv", "kicad", "step"}
MEDIA = {
    "stl": "model/stl",
    "3mf": "model/3mf",
    "bom_csv": "text/csv",
    "wiring_csv": "text/csv",
    "kicad": "application/zip",
    "step": "model/step",
}


class ExportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_rel(path: str) -> str | None:
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


# What each case finish is printed or cut from (Color.finish.preset, SPEC common types).
FINISH_MAKES = {
    "matte": "PLA",
    "satin": "PETG",
    "gloss": "moulded ABS",
    "silk": "silk PLA",
    "frosted": "translucent PETG",
    "clear": "clear acrylic or resin",
    "smoke": "tinted acrylic",
    "metal": "anodised aluminium",
}


def case_material_note(enc: dict[str, Any]) -> str:
    """', frosted: translucent PETG, #7FB5E6' for the BOM, or '' when no finish was chosen."""
    color = enc.get("color") or {}
    preset = (color.get("finish") or {}).get("preset")
    if preset not in FINISH_MAKES:
        return ""
    hex_ = color.get("hex")
    return f", {preset}: {FINISH_MAKES[preset]}" + (f", {hex_}" if hex_ else "")


def asset_path(url: str | None) -> Path | None:
    """Local file behind an /assets/ URL, or None when it is not on this server."""
    if not url or not url.startswith("/assets/"):
        return None
    # A ?v=<hash> suffix only versions the URL; the file is the path before it.
    rel = _safe_rel(url.split("?", 1)[0].split("#", 1)[0][len("/assets/") :])
    if rel is None:
        return None
    root = load_settings().assets_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def _assets_of(items: list[dict[str, Any]], kind: str) -> tuple[list[Path], list[str]]:
    found: list[Path] = []
    missing: list[str] = []
    for item in items:
        refs = [a for a in item.get("assets") or [] if a.get("kind") == kind]
        if not refs:
            continue
        path = asset_path(refs[0].get("url"))
        if path is None:
            missing.append(str(refs[0].get("url")))
        else:
            found.append(path)
    return found, missing


# ---------------------------------------------------------------- KiCad pcb parsing


_FP_RE = re.compile(r'\(footprint\s+"([^"]+)"')
_PROP_RE = re.compile(r'\(property\s+"(Reference|Value)"\s+"([^"]*)"')


def _footprint_blocks(text: str) -> list[str]:
    blocks = []
    for m in _FP_RE.finditer(text):
        depth, i = 0, m.start()
        for j in range(m.start(), len(text)):
            c = text[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(text[i : j + 1])
                    break
    return blocks


def parse_kicad_pcb(text: str) -> list[dict[str, Any]]:
    """Footprints of a .kicad_pcb: lib_id, reference, value and pad -> net pairs."""
    out = []
    for block in _footprint_blocks(text):
        lib_id = _FP_RE.match(block.strip())
        props = dict(_PROP_RE.findall(block))
        pads = []
        for pad in re.finditer(r'\(pad\s+"([^"]*)"', block):
            depth, k = 0, pad.start()
            for j in range(pad.start(), len(block)):
                if block[j] == "(":
                    depth += 1
                elif block[j] == ")":
                    depth -= 1
                    if depth == 0:
                        body = block[k : j + 1]
                        net = re.search(r'\(net\s+(?:\d+\s+)?"([^"]*)"\)', body)
                        if net and net.group(1):
                            pads.append((pad.group(1), net.group(1)))
                        break
        out.append(
            {
                "lib_id": lib_id.group(1) if lib_id else "",
                "ref": props.get("Reference", ""),
                "value": props.get("Value", ""),
                "pads": pads,
            }
        )
    return out


def _kicad_lib_info(lib_id: str) -> tuple[str, str]:
    lib = lib_id.split(":", 1)[0]
    if lib and (KICAD_SHARE / "footprints" / f"{lib}.pretty").is_dir():
        return f"{KICAD_FOOTPRINTS_URL}/-/tree/master/{lib}.pretty", KICAD_LIB_LICENCE
    return "", ""


def _board_footprints(build: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    paths, _ = _assets_of(build.get("boards") or [], "kicad_pcb")
    out = []
    for path in paths:
        for fp in parse_kicad_pcb(path.read_text(errors="replace")):
            out.append((path.stem, fp))
    return out


# ---------------------------------------------------------------- CSVs


def bom_csv(build: dict[str, Any]) -> str:
    rows: dict[str, dict[str, Any]] = {}
    for part in build.get("parts") or []:
        card = part.get("card") or {}
        row = rows.setdefault(
            part["part_id"],
            {
                "part_id": part["part_id"],
                "name": card.get("display_name", part["part_id"]),
                "quantity": 0,
                "instances": [],
                "lib_id": "",
                "licence": card.get("licence_spdx", ""),
                "commercial_ok": card.get("commercial_ok", ""),
                "source_url": card.get("source_url") or "",
            },
        )
        row["quantity"] += int(part.get("quantity", 1) or 1)
        row["instances"].append(part["instance_id"])
    for board, fp in _board_footprints(build):
        key = f"kicad:{fp['lib_id']}@{fp['value']}"
        url, lic = _kicad_lib_info(fp["lib_id"])
        row = rows.setdefault(
            key,
            {
                "part_id": key,
                "name": fp["value"] or fp["lib_id"],
                "quantity": 0,
                "instances": [],
                "lib_id": fp["lib_id"],
                "licence": lic,
                "commercial_ok": "",
                "source_url": url,
            },
        )
        row["quantity"] += 1
        row["instances"].append(f"{board}:{fp['ref']}")
    for enc in build.get("enclosures") or []:
        if enc.get("kind") == "generated":
            rows[enc["enclosure_id"]] = {
                "part_id": enc["enclosure_id"],
                "name": "Generated case (tray + bezel)" + case_material_note(enc),
                "quantity": 1,
                "instances": [enc["enclosure_id"]],
                "lib_id": "",
                "licence": "",
                "commercial_ok": "",
                "source_url": "",
            }
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    cols = [
        "part_id",
        "name",
        "quantity",
        "instances",
        "lib_id",
        "licence",
        "commercial_ok",
        "source_url",
    ]
    writer.writerow(cols)
    for row in rows.values():
        writer.writerow([" ".join(row[c]) if c == "instances" else row[c] for c in cols])
    return out.getvalue()


def wiring_csv(build: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "source",
            "signal",
            "from_instance",
            "from_pin",
            "to_instance",
            "to_pin",
            "type",
            "connection_id",
        ]
    )
    for conn in build.get("connections") or []:
        nets = conn.get("nets") or [{"signal": conn.get("label") or conn.get("type", "")}]
        for net in nets:
            writer.writerow(
                [
                    "connection",
                    net.get("signal", ""),
                    conn["from"].get("instance_id", ""),
                    net.get("from_pin") or conn["from"].get("interface_id", ""),
                    conn["to"].get("instance_id", ""),
                    net.get("to_pin") or conn["to"].get("interface_id", ""),
                    conn.get("type", ""),
                    conn.get("connection_id", ""),
                ]
            )
    for board in build.get("boards") or []:
        for net in board.get("nets") or []:
            for mem in net.get("members") or []:
                writer.writerow(
                    [
                        "board_net",
                        net["name"],
                        mem.get("instance_id", ""),
                        mem.get("pin", ""),
                        "",
                        "",
                        net.get("kind", ""),
                        board.get("board_id", ""),
                    ]
                )
    for board_name, fp in _board_footprints(build):
        for pad, net in fp["pads"]:
            writer.writerow(
                ["kicad_pcb", net, f"{board_name}:{fp['ref']}", pad, "", "", fp["lib_id"], ""]
            )
    return out.getvalue()


# ---------------------------------------------------------------- meshes


def _case_parts(build: dict[str, Any], kind: str) -> list[MeshPart]:
    parts: list[MeshPart] = []
    missing: list[str] = []
    for enc in build.get("enclosures") or []:
        refs = [a for a in enc.get("assets") or [] if a.get("kind") == kind]
        if enc.get("kind") == "none" or not refs:
            continue
        path = asset_path(refs[0].get("url"))
        if path is None:
            missing.append(str(refs[0].get("url")))
            continue
        offset = np.asarray(enc.get("position_mm") or [0, 0, 0], dtype=np.float64)
        color = (enc.get("color") or {}).get("hex") or "#9E9E9E"
        data = path.read_bytes()
        if kind == "stl":
            v = (read_stl(data) + offset).reshape(-1, 3)
            tris = np.arange(len(v)).reshape(-1, 3)
            parts.append(MeshPart(enc["enclosure_id"], v, tris, None, color))
        else:
            for i, (v, t) in enumerate(read_3mf(data)):
                parts.append(MeshPart(f"{enc['enclosure_id']}_{i}", v + offset, t, None, color))
    if missing or not parts:
        detail = f" ({', '.join(missing)})" if missing else ""
        raise ExportError("E_ASSET_MISSING", f"No {kind} file for the case on this server{detail}.")
    return parts


def _step(build: dict[str, Any]) -> bytes:
    boards = build.get("boards") or []
    paths, missing = _assets_of(boards, "kicad_pcb")
    if not paths:
        detail = f" ({', '.join(missing)})" if missing else ""
        raise ExportError("E_ASSET_MISSING", f"No KiCad board file on this server{detail}.")
    exe = shutil.which("kicad-cli") or "/opt/homebrew/bin/kicad-cli"
    if not Path(exe).exists():
        raise ExportError("E_ASSET_MISSING", "kicad-cli is not installed, so no STEP export.")
    cache = load_settings().assets_dir / "cache" / "step"
    cache.mkdir(parents=True, exist_ok=True)
    outs: list[tuple[str, bytes]] = []
    for path in paths:
        key = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
        dest = cache / f"{key}.step"
        if not dest.exists():
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "board.step"
                proc = subprocess.run(
                    [
                        exe,
                        "pcb",
                        "export",
                        "step",
                        "--subst-models",
                        "--force",
                        "-o",
                        str(out),
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=STEP_TIMEOUT_S,
                    check=False,
                )
                if proc.returncode != 0 or not out.exists():
                    raise ExportError(
                        "E_ASSET_MISSING",
                        f"kicad-cli STEP export failed for {path.name}: "
                        f"{(proc.stderr or proc.stdout).strip()[-200:]}",
                    )
                shutil.move(str(out), dest)
        outs.append((f"{path.stem}.step", dest.read_bytes()))
    if len(outs) == 1:
        return outs[0][1]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in outs:
            zf.writestr(name, data)
    return buf.getvalue()


def _kicad_zip(build: dict[str, Any]) -> bytes:
    boards = build.get("boards") or []
    paths, missing = _assets_of(boards, "kicad_pcb")
    if not paths:
        detail = f" ({', '.join(missing)})" if missing else ""
        raise ExportError("E_ASSET_MISSING", f"No KiCad board file on this server{detail}.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            zf.writestr(f"{path.stem}/{path.stem}.kicad_pcb", path.read_bytes())
            pro = {"meta": {"filename": f"{path.stem}.kicad_pro", "version": 1}}
            zf.writestr(f"{path.stem}/{path.stem}.kicad_pro", json.dumps(pro, indent=2))
        zf.writestr("bom.csv", bom_csv(build))
        zf.writestr("wiring.csv", wiring_csv(build))
        lines = [f"Bara KiCad export of {build.get('build_id')}."]
        if missing:
            lines.append("Boards not bundled because their file is not on this server:")
            lines += [f"- {m}" for m in missing]
        zf.writestr("MANIFEST.txt", "\n".join(lines) + "\n")
    return buf.getvalue()


def export(build: dict[str, Any], fmt: str) -> tuple[bytes, str]:
    """(file bytes, media type) for one export format; ExportError when it cannot exist."""
    if fmt not in FORMATS:
        raise ExportError("E_BAD_MESSAGE", f"format must be one of {sorted(FORMATS)}.")
    if fmt == "bom_csv":
        data = bom_csv(build).encode()
    elif fmt == "wiring_csv":
        data = wiring_csv(build).encode()
    elif fmt == "stl":
        data = write_stl(_case_parts(build, "stl"))
    elif fmt == "3mf":
        data = write_3mf(_case_parts(build, "3mf"))
    elif fmt == "kicad":
        data = _kicad_zip(build)
    else:
        data = _step(build)
    return data, MEDIA[fmt]
