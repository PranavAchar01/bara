"""Measure a real object or space from one phone photo with OpenCV 5.

A printed ArUco marker of known size lies on the same flat surface as the thing being measured.
The marker's four corners give a homography from image pixels to millimetres on that plane, so the
photo is rectified to a true top-down view first, and every length after that is in mm.

Segmentation runs as a list of strategies. Each one returns candidates with quality checks, so the
caller (the fit agent) can see why a strategy failed and try the next one instead of trusting the
first contour it finds.

This module imports only OpenCV and NumPy, so the same file runs inside the AWS Lambda package.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import cv2
import numpy as np

ARUCO_DICT = cv2.aruco.DICT_4X4_50
MARKER_ID = 7  # the id on the printed sheet; any other 4x4 code is a keyboard key or a pattern
MIN_MARKER_PX = 40.0  # mean side after downscaling; smaller means a fleck, not the 40 mm sheet
MAX_SIDE_PX = 1600  # photos are downscaled to this before anything else
PX_PER_MM = 4.0  # resolution of the rectified top-down view
HALF_SPAN_MM = 450.0  # rectified view covers at most this far from the marker in each direction
MIN_AREA_MM2 = 400.0  # 2 cm x 2 cm: anything smaller is noise or a shadow fleck
STRATEGIES = ("lab_otsu", "adaptive", "edges")


def _decode(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not an image")
    h, w = img.shape[:2]
    scale = MAX_SIDE_PX / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _enhance(img: np.ndarray) -> np.ndarray:
    """Local contrast boost (CLAHE on L) for dim or glary photos."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def find_marker(img: np.ndarray) -> dict[str, Any] | None:
    """The printed marker (id MARKER_ID, at least MIN_MARKER_PX a side): corners (px) and skew."""
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT), params)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None or len(ids) == 0:
        return None
    ids = np.asarray(ids).reshape(-1)
    found = []
    for i, marker_id in enumerate(ids):
        quad = corners[i].reshape(4, 2).astype(np.float64)
        sides = [float(np.linalg.norm(quad[j] - quad[(j + 1) % 4])) for j in range(4)]
        if int(marker_id) == MARKER_ID and sum(sides) / 4 >= MIN_MARKER_PX:
            found.append((cv2.contourArea(quad.astype(np.float32)), quad, sides))
    if not found:
        return None
    _, quad, sides = max(found, key=lambda f: f[0])
    return {
        "id": MARKER_ID,
        "corners_px": quad.round(2).tolist(),
        "side_px": round(sum(sides) / 4, 2),
        # 1.0 is a square on screen; far from 1 means a steep camera angle
        "skew": round(min(sides) / max(sides), 3),
        "count": len(found),
    }


def rectify(img: np.ndarray, quad: np.ndarray, marker_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """Warp the photo to a top-down view at PX_PER_MM, marker centred near the middle.

    Returns the rectified image and the 3x3 homography that maps photo px to rectified px.
    """
    s = marker_mm * PX_PER_MM
    dst = np.array([[0, 0], [s, 0], [s, s], [0, s]], dtype=np.float64)
    h_marker = cv2.getPerspectiveTransform(quad.astype(np.float32), dst.astype(np.float32))
    h, w = img.shape[:2]
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32).reshape(-1, 1, 2)
    out = cv2.perspectiveTransform(corners, h_marker).reshape(-1, 2)
    span = HALF_SPAN_MM * PX_PER_MM
    lo = np.maximum(out.min(axis=0), [-span + s / 2, -span + s / 2])
    hi = np.minimum(out.max(axis=0), [span + s / 2, span + s / 2])
    shift = np.array([[1, 0, -lo[0]], [0, 1, -lo[1]], [0, 0, 1]], dtype=np.float64)
    full = shift @ h_marker
    size = (int(np.ceil(hi[0] - lo[0])), int(np.ceil(hi[1] - lo[1])))
    top = cv2.warpPerspective(img, full, size, flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
    return top, full


def _valid_mask(top: np.ndarray, full: np.ndarray, src_shape: tuple[int, int]) -> np.ndarray:
    """Pixels of the rectified view that came from inside the photo."""
    h, w = src_shape
    ones = np.full((h, w), 255, np.uint8)
    m = cv2.warpPerspective(ones, full, (top.shape[1], top.shape[0]), flags=cv2.INTER_NEAREST)
    return cv2.erode(m, np.ones((9, 9), np.uint8))


def sheet_mask(top: np.ndarray, valid: np.ndarray, marker_poly: np.ndarray) -> np.ndarray:
    """The marker plus the paper it is printed on, found by flooding the white margin."""
    poly = np.zeros(top.shape[:2], np.uint8)
    cv2.fillPoly(poly, [marker_poly.astype(np.int32)], 255)
    near = cv2.dilate(poly, np.ones((int(6 * PX_PER_MM),) * 2, np.uint8))
    blur = cv2.GaussianBlur(top, (5, 5), 0)
    flood = np.zeros((top.shape[0] + 2, top.shape[1] + 2), np.uint8)
    c = marker_poly.mean(axis=0)
    for p in marker_poly:
        q = p + (p - c) / np.linalg.norm(p - c) * 3 * PX_PER_MM  # 3 mm out, on the white margin
        x, y = int(q[0]), int(q[1])
        if 0 <= x < top.shape[1] and 0 <= y < top.shape[0] and not flood[y + 1, x + 1]:
            cv2.floodFill(
                blur,
                flood,
                (x, y),
                0,
                (12, 12, 12),
                (12, 12, 12),
                4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8),
            )
    sheet = flood[1:-1, 1:-1]
    if np.count_nonzero(sheet) > 0.3 * max(np.count_nonzero(valid), 1):
        sheet = np.zeros_like(sheet)  # the flood leaked into a white desk: keep only the marker
    sheet = cv2.bitwise_or(sheet, near)
    return cv2.dilate(sheet, np.ones((int(2 * PX_PER_MM),) * 2, np.uint8))


def _segment(top: np.ndarray, valid: np.ndarray, marker_poly: np.ndarray, how: str) -> np.ndarray:
    """Binary mask of 'not the surface' for one strategy."""
    blur = cv2.GaussianBlur(top, (7, 7), 0)
    sheet = sheet_mask(top, valid, marker_poly)
    surface = (valid > 0) & (sheet == 0)
    if how == "lab_otsu":
        lab = cv2.cvtColor(blur, cv2.COLOR_BGR2LAB).astype(np.float32)
        ring = cv2.subtract(valid, cv2.erode(valid, np.ones((41, 41), np.uint8)))
        ring[sheet > 0] = 0
        bg = np.median(lab[ring > 0], axis=0) if np.count_nonzero(ring) else np.median(lab, (0, 1))
        dist = np.linalg.norm(lab - bg, axis=2)
        dist = np.clip(dist / max(float(np.percentile(dist[surface], 99.5)), 1e-3) * 255, 0, 255)
        dist = dist.astype(np.uint8)
        t, _ = cv2.threshold(
            dist[surface].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        mask = np.where(dist > max(t, 40), 255, 0).astype(np.uint8)
    elif how == "adaptive":
        gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
        mask = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 6
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        filled = np.zeros_like(mask)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(filled, cnts, -1, 255, cv2.FILLED)
        mask = filled
    else:  # edges
        gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        edges = cv2.dilate(edges, np.ones((5, 5), np.uint8))
        mask = np.zeros_like(edges)
        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(mask, cnts, -1, 255, cv2.FILLED)
    mask = cv2.bitwise_and(mask, valid)
    # the marker and the paper it sits on are not the object
    mask[sheet > 0] = 0
    k = np.ones((7, 7), np.uint8)
    return cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, k), cv2.MORPH_CLOSE, k)


def _shape(cnt: np.ndarray) -> dict[str, Any]:
    area_px = cv2.contourArea(cnt)
    perim = cv2.arcLength(cnt, True)
    (cx, cy), (rw, rh), angle = cv2.minAreaRect(cnt)
    hull = cv2.convexHull(cnt)
    solidity = area_px / max(cv2.contourArea(hull), 1e-6)
    rect_fill = area_px / max(rw * rh, 1e-6)
    circ = 4 * np.pi * area_px / max(perim * perim, 1e-6)
    if circ > 0.86 and abs(rw - rh) / max(rw, rh) < 0.12:
        kind = "round"
    elif rect_fill > 0.88:
        kind = "rectangle"
    elif solidity > 0.95 and 0.72 < rect_fill < 0.84:
        kind = "oval"
    else:
        kind = "freeform"
    poly = cv2.approxPolyDP(cnt, 0.006 * perim, True).reshape(-1, 2) / PX_PER_MM
    w_mm, d_mm = sorted((rw / PX_PER_MM, rh / PX_PER_MM), reverse=True)
    return {
        "width_mm": round(float(w_mm), 1),
        "depth_mm": round(float(d_mm), 1),
        "area_mm2": round(float(area_px / PX_PER_MM**2), 1),
        "angle_deg": round(float(angle), 1),
        "center_mm": [round(float(cx / PX_PER_MM), 1), round(float(cy / PX_PER_MM), 1)],
        "kind": kind,
        "rect_fill": round(float(rect_fill), 3),
        "solidity": round(float(solidity), 3),
        "circularity": round(float(circ), 3),
        "outline_mm": poly.round(1).tolist(),
    }


def _candidates(
    mask: np.ndarray, valid: np.ndarray, marker_center: tuple[float, float]
) -> list[dict[str, Any]]:
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    edge = cv2.subtract(np.full_like(valid, 255), cv2.erode(valid, np.ones((5, 5), np.uint8)))
    edge = cv2.dilate(edge, np.ones((7, 7), np.uint8))
    out = []
    for c in cnts:
        if cv2.contourArea(c) / PX_PER_MM**2 < MIN_AREA_MM2:
            continue
        # the sheet the marker is printed on is not the object
        if cv2.pointPolygonTest(c, marker_center, False) >= 0:
            continue
        m = np.zeros_like(mask)
        cv2.drawContours(m, [c], -1, 255, 2)
        touches = bool(np.count_nonzero(cv2.bitwise_and(m, edge)))
        out.append({"contour": c, "touches_edge": touches, **_shape(c)})
    out.sort(key=lambda d: d["area_mm2"], reverse=True)
    return out


def checks(cands: list[dict[str, Any]], frame_mm2: float) -> list[str]:
    """Reasons a strategy's best candidate should not be trusted ([] means it passed)."""
    if not cands:
        return ["no_object"]
    best = cands[0]
    issues = []
    if best["touches_edge"]:
        issues.append("cut_off")
    if best["area_mm2"] > 0.8 * frame_mm2:
        issues.append("whole_frame")
    if best["solidity"] < 0.6:
        issues.append("ragged")
    if len(cands) > 1 and cands[1]["area_mm2"] > 0.6 * best["area_mm2"]:
        issues.append("two_objects")
    return issues


def _annotate(top: np.ndarray, marker_poly: np.ndarray, best: dict[str, Any] | None) -> str:
    vis = top.copy()
    cv2.polylines(vis, [marker_poly.astype(np.int32)], True, (60, 160, 255), 3)
    if best is not None:
        c = best["contour"]
        cv2.drawContours(vis, [c], -1, (40, 200, 90), 3)
        box = cv2.boxPoints(cv2.minAreaRect(c)).astype(np.int32)
        cv2.polylines(vis, [box], True, (30, 30, 230), 2)
        label = f"{best['width_mm']:.0f} x {best['depth_mm']:.0f} mm"
        x, y = int(box[:, 0].min()), max(30, int(box[:, 1].min()) - 12)
        cv2.putText(
            vis, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 5, cv2.LINE_AA
        )
        cv2.putText(vis, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 2, cv2.LINE_AA)
    scale = 900 / max(vis.shape[:2])
    if scale < 1:
        vis = cv2.resize(vis, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return base64.b64encode(jpg.tobytes()).decode("ascii") if ok else ""


def measure(
    data: bytes,
    marker_mm: float = 40.0,
    strategies: tuple[str, ...] = STRATEGIES,
    annotate: bool = True,
    enhance: bool = False,
) -> dict[str, Any]:
    """One photo in, the footprint of the main object out (or why there is none).

    Every strategy tried is reported with its issues, so a caller can decide what to do next.
    """
    t0 = time.perf_counter()
    img = _decode(data)
    if enhance:
        img = _enhance(img)
    result: dict[str, Any] = {
        "opencv": cv2.__version__,
        "image_px": [int(img.shape[1]), int(img.shape[0])],
        "marker_mm": marker_mm,
        "enhanced": enhance,
        "tried": [],
    }
    marker = find_marker(img)
    result["marker"] = marker
    if marker is None:
        result.update(
            status="no_marker", object=None, ms=round((time.perf_counter() - t0) * 1e3, 1)
        )
        return result
    quad = np.array(marker["corners_px"], dtype=np.float64)
    top, full = rectify(img, quad, marker_mm)
    valid = _valid_mask(top, full, img.shape[:2])
    marker_top = cv2.perspectiveTransform(quad.reshape(-1, 1, 2), full).reshape(-1, 2)
    frame_mm2 = float(np.count_nonzero(valid)) / PX_PER_MM**2
    chosen: dict[str, Any] | None = None
    for how in strategies:
        mc = (float(marker_top[:, 0].mean()), float(marker_top[:, 1].mean()))
        cands = _candidates(_segment(top, valid, marker_top, how), valid, mc)
        issues = checks(cands, frame_mm2)
        summary = {k: v for k, v in cands[0].items() if k != "contour"} if cands else None
        result["tried"].append({"strategy": how, "issues": issues, "best": summary})
        if not issues:
            chosen = {"strategy": how, **cands[0]}
            break
    if chosen is None:
        # nothing passed: keep the strategy whose best candidate had the fewest issues, flagged
        tried = [t for t in result["tried"] if t["best"] is not None]
        result["status"] = "unsure" if tried else "no_object"
        pick = min(tried, key=lambda t: len(t["issues"])) if tried else None
        result["object"] = pick["best"] if pick else None
        best_for_vis = None
    else:
        result["status"] = "ok"
        result["object"] = {k: v for k, v in chosen.items() if k != "contour"}
        best_for_vis = chosen
    result["rectified_mm"] = [
        round(top.shape[1] / PX_PER_MM, 1),
        round(top.shape[0] / PX_PER_MM, 1),
    ]
    if annotate:
        result["annotated_jpg_b64"] = _annotate(top, marker_top, best_for_vis)
    result["ms"] = round((time.perf_counter() - t0) * 1e3, 1)
    return result


def marker_png(marker_id: int = MARKER_ID, marker_mm: float = 40.0, dpi: int = 300) -> bytes:
    """A printable marker: the black square is exactly marker_mm wide at the given dpi."""
    side = round(marker_mm / 25.4 * dpi)
    mark = cv2.aruco.generateImageMarker(
        cv2.aruco.getPredefinedDictionary(ARUCO_DICT), marker_id, side
    )
    border = round(10 / 25.4 * dpi)
    page = cv2.copyMakeBorder(
        mark, border, border * 3, border, border, cv2.BORDER_CONSTANT, value=255
    )
    text = f"Fit marker  id {marker_id}  {marker_mm:g} mm  print at 100%"
    cv2.putText(
        page,
        text,
        (border, side + border + round(border * 1.6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        dpi / 300 * 0.9,
        0,
        2,
        cv2.LINE_AA,
    )
    ok, png = cv2.imencode(".png", page)
    if not ok:
        raise RuntimeError("png encode failed")
    return png.tobytes()
