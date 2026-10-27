"""Synthetic phone photos with known ground truth, for tests and the evaluation script.

A flat table is drawn in millimetres, a printed marker and one object are placed on it, then the
whole plane is pushed through a random camera homography with lighting falloff, blur, sensor noise
and JPEG compression. The object's true width and depth are known exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from bara.vision.measure import ARUCO_DICT

SCENE_PX_PER_MM = 5.0


@dataclass
class Scene:
    jpg: bytes
    width_mm: float
    depth_mm: float
    kind: str
    tilt_deg: float


def _table(rng: np.random.Generator, w: int, h: int) -> np.ndarray:
    base = np.array(rng.choice([[200, 205, 210], [120, 150, 180], [90, 95, 100], [215, 225, 230]]))
    noise = cv2.GaussianBlur(rng.normal(0, 18, (h // 8, w // 8)).astype(np.float32), (0, 0), 3)
    noise = cv2.resize(noise, (w, h))
    img = np.clip(base[None, None, :] + noise[..., None], 0, 255).astype(np.uint8)
    return img


def make_scene(
    rng: np.random.Generator,
    width_mm: float,
    depth_mm: float,
    kind: str = "rectangle",
    marker_mm: float = 40.0,
    tilt: float = 0.18,
    marker: bool = True,
    center_mm: tuple[float, float] = (310.0, 210.0),
    second: tuple[float, float] | None = None,
) -> Scene:
    """`marker=False`, a `center_mm` near the edge, or a `second` object of (w, d) mm make the
    failure cases the agent has to catch."""
    k = SCENE_PX_PER_MM
    W, H = int(520 * k), int(400 * k)
    img = _table(rng, W, H)
    # marker on white paper, upper left
    side = int(marker_mm * k)
    mark = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(ARUCO_DICT), 7, side)
    pad = int(8 * k)
    mx, my = int(95 * k), int(95 * k)
    if marker:
        img[my - pad : my + side + pad, mx - pad : mx + side + pad] = 250
        img[my : my + side, mx : mx + side] = mark[..., None]
    # the object, rotated, right of the marker
    color = tuple(
        int(c) for c in rng.choice([[40, 40, 45], [30, 60, 160], [180, 70, 40], [60, 140, 60]])
    )
    cx, cy = center_mm[0] * k, center_mm[1] * k
    ang = float(rng.uniform(-35, 35))
    if kind == "round":
        cv2.ellipse(
            img,
            (int(cx), int(cy)),
            (int(width_mm * k / 2), int(depth_mm * k / 2)),
            ang,
            0,
            360,
            color,
            cv2.FILLED,
            cv2.LINE_AA,
        )
    else:
        box = cv2.boxPoints(((cx, cy), (width_mm * k, depth_mm * k), ang)).astype(np.int32)
        cv2.fillPoly(img, [box], color, cv2.LINE_AA)
    if second is not None:
        box = cv2.boxPoints(((200 * k, 320 * k), (second[0] * k, second[1] * k), 10.0))
        cv2.fillPoly(img, [box.astype(np.int32)], color, cv2.LINE_AA)
    # camera: random perspective, tilt scales how strong it is
    src = np.array([[0, 0], [W, 0], [W, H], [0, H]], np.float32)
    j = tilt * min(W, H)
    dst = src + rng.uniform(-j, j, src.shape).astype(np.float32)
    dst -= dst.min(axis=0)
    hm = cv2.getPerspectiveTransform(src, dst)
    out_w, out_h = int(dst[:, 0].max()), int(dst[:, 1].max())
    photo = cv2.warpPerspective(img, hm, (out_w, out_h))
    # crop to the part of the frame the table fills, like a real photo of a desk
    x0, x1 = int(max(dst[0, 0], dst[3, 0])) + 2, int(min(dst[1, 0], dst[2, 0])) - 2
    y0, y1 = int(max(dst[0, 1], dst[1, 1])) + 2, int(min(dst[2, 1], dst[3, 1])) - 2
    photo = photo[y0:y1, x0:x1]
    out_h, out_w = photo.shape[:2]
    yy, xx = np.mgrid[0:out_h, 0:out_w].astype(np.float32)
    fall = 1.0 - 0.25 * (
        ((xx - out_w * rng.uniform(0.2, 0.8)) / out_w) ** 2 + ((yy - out_h * 0.4) / out_h) ** 2
    )
    photo = np.clip(photo.astype(np.float32) * fall[..., None], 0, 255)
    photo = cv2.GaussianBlur(photo, (0, 0), float(rng.uniform(0.6, 1.4)))
    photo = np.clip(photo + rng.normal(0, 4, photo.shape), 0, 255).astype(np.uint8)
    ok, jpg = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    tilt_deg = float(np.degrees(np.arctan(j / min(W, H))))
    return Scene(jpg.tobytes(), width_mm, depth_mm, kind, tilt_deg)
