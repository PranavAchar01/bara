"""KiCad's own evaluation of a routed board, as checks and a benchmark summary.

kicad-cli DRC reports every violation by type; the router and the copper tell how complete
and how costly the routing is; the net list tells whether a net can work at all (a net
with one pin is wired to nothing, the board-level stand-in for an ERC "pin not connected").
None of it depends on what device the board is for.
"""

from __future__ import annotations

from typing import Any

SEVERITY = {"error": "error", "warning": "warning"}


def evaluate(bid: str, nets: list[dict], drc: dict, routing: dict, timings: dict) -> dict:
    """Return {"summary": ..., "checks": [...]} for one board."""
    subjects = [{"board_id": bid}]
    checks: list[dict[str, Any]] = []
    titles = drc.get("titles") or {}
    for key, count in sorted((drc.get("by_type") or {}).items()):
        severity, _, kind = key.partition(":")
        title = titles.get(key) or kind.replace("_", " ")
        checks.append(
            {
                "check_key": f"board.drc.{kind}:{bid}",
                "rule_id": "board.drc.violation",
                "status": "fail" if severity == "error" else "unknown",
                "severity": SEVERITY.get(severity, "info"),
                "message": f"KiCad DRC {severity}: {title} ({count}x)",
                "subjects": subjects,
                "measured": count,
                "limit": 0,
                "unit": "count",
                "stage": "board",
            }
        )

    wired = [n for n in nets if len(n.get("members") or []) >= 2]
    dangling = [str(n.get("name") or n.get("net_id") or "?") for n in nets if n not in wired]
    checks.append(
        {
            "check_key": f"board.nets.connected:{bid}",
            "rule_id": "board.nets.connected",
            "status": "fail" if dangling else "pass",
            "severity": "warning",
            "message": (
                f"Nets wired to one pin only: {', '.join(dangling[:6])}"
                + (f" and {len(dangling) - 6} more" if len(dangling) > 6 else "")
                if dangling
                else f"All {len(nets)} nets join two or more pins"
            ),
            "subjects": subjects,
            "measured": len(dangling),
            "limit": 0,
            "unit": "count",
            "stage": "board",
        }
    )

    open_nets = set(routing.get("unrouted_nets") or drc.get("unconnected_nets") or [])
    names = {str(n.get("name") or "") for n in wired}
    complete = 100.0 if not names else 100.0 * len(names - open_nets) / len(names)
    track = routing.get("track_mm") or {}
    summary = {
        "drc_errors": int(drc.get("errors", 0)),
        "drc_warnings": int(drc.get("warnings", 0)),
        "unconnected": int(drc.get("unconnected", 0)),
        "nets": len(nets),
        "dangling_nets": len(dangling),
        "routed_pct": round(complete, 1),
        "segments": routing.get("segments"),
        "vias": routing.get("vias"),
        "track_mm": track,
        "track_total_mm": round(sum(track.values()), 1) if track else None,
        "strategy": routing.get("strategy"),
        "attempts": len(routing.get("attempts") or []),
        "route_s": timings.get("route_s"),
        "drc_s": timings.get("drc_s"),
        "total_s": timings.get("total_s"),
    }
    copper = f", {summary['track_total_mm']:.0f} mm of track" if track else ""
    checks.append(
        {
            "check_key": f"board.bench:{bid}",
            "rule_id": "board.bench",
            "status": "pass" if complete >= 100.0 else "fail",
            "severity": "info",
            "message": (
                f"Routing benchmark: {complete:.0f}% of nets routed, "
                f"{summary['segments'] or 0} tracks, {summary['vias'] or 0} vias{copper}, "
                f"{summary['attempts']} router attempt(s) in {summary['route_s'] or 0:.0f} s"
            ),
            "subjects": subjects,
            "measured": round(complete, 1),
            "limit": 100,
            "unit": "%",
            "stage": "board",
        }
    )
    return {"summary": summary, "checks": checks}
