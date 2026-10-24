"""PCB Calculator formulas (KiCad's calculator is GUI-only), implemented from IPC-2221.

Current limit of a conductor: I = k * dT^0.44 * A^0.725 with A the cross-section in square mils,
dT the allowed temperature rise in degC, k = 0.048 for external layers and 0.024 for internal.
"""

from __future__ import annotations

import math

OZ_MM = 0.035  # 1 oz/ft^2 copper
MIL_MM = 0.0254
K_EXTERNAL = 0.048
K_INTERNAL = 0.024


def _area_mil2(width_mm: float, copper_oz: float) -> float:
    return (width_mm / MIL_MM) * (copper_oz * OZ_MM / MIL_MM)


def track_current_a(
    width_mm: float, copper_oz: float = 1.0, rise_c: float = 10.0, external: bool = True
) -> float:
    """Largest continuous current a track of this width carries within `rise_c` of heating."""
    k = K_EXTERNAL if external else K_INTERNAL
    return k * rise_c**0.44 * _area_mil2(width_mm, copper_oz) ** 0.725


def track_width_mm(
    current_a: float, copper_oz: float = 1.0, rise_c: float = 10.0, external: bool = True
) -> float:
    """Narrowest track that carries `current_a` within `rise_c` of heating."""
    k = K_EXTERNAL if external else K_INTERNAL
    area = (current_a / (k * rise_c**0.44)) ** (1 / 0.725)
    return area / (copper_oz * OZ_MM / MIL_MM) * MIL_MM


def via_current_a(drill_mm: float, plating_mm: float = 0.025, rise_c: float = 10.0) -> float:
    """Via barrel as a tube of copper (outer diameter = drill + 2 * plating), same formula."""
    d_out = drill_mm + 2 * plating_mm
    area_mm2 = math.pi / 4 * (d_out**2 - drill_mm**2)
    area_mil2 = area_mm2 / MIL_MM**2
    return K_EXTERNAL * rise_c**0.44 * area_mil2**0.725
