"""Routed power tracks of a .kicad_pcb against the current on their net (IPC-2221)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

_SEG = re.compile(
    r"\(segment\s+\(start [^)]*\)\s*\(end [^)]*\)\s*\(width ([\d.]+)\)\s*"
    r'\(layer "([^"]+)"\)\s*\(net "([^"]*)"\)'
)


def read_tracks(pcb: Path) -> tuple[dict[str, list[tuple[float, str]]], dict[str, list[float]]]:
    """({net: [(width_mm, layer)]}, {net: [via drill_mm]})."""
    text = pcb.read_text()
    segs: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for w, layer, net in _SEG.findall(text):
        segs[net].append((float(w), layer))
    vias: dict[str, list[float]] = defaultdict(list)
    for block in text.split("\n\t(via")[1:]:
        head = block[:400]
        drill = re.search(r"\(drill ([\d.]+)\)", head)
        net = re.search(r'\(net "([^"]*)"\)', head)
        if drill and net:
            vias[net.group(1)].append(float(drill.group(1)))
    return segs, vias
