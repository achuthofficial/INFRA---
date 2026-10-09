"""
Stage 5 -- render the fill/cut mask as a colored overlay on the original
ROI, with the grid-cell boundaries drawn on top for auditability.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import PipelineConfig
from .section import Section
from .area import between_mask


def colour_composite(s: Section, cfg: PipelineConfig) -> np.ndarray:
    ss, subdiv, alpha = cfg.supersample, cfg.subdiv, cfg.overlay_alpha
    fill, cut = between_mask(s, ss)
    fill = cv2.resize(fill.astype(np.uint8), (s.W, s.H), interpolation=cv2.INTER_AREA).astype(bool)
    cut = cv2.resize(cut.astype(np.uint8), (s.W, s.H), interpolation=cv2.INTER_AREA).astype(bool)

    base = cv2.cvtColor(255 - s.roi * 255, cv2.COLOR_GRAY2BGR).astype(float)
    lay = base.copy()
    lay[fill] = cfg.fill_color_bgr
    lay[cut] = cfg.cut_color_bgr
    out = np.where((fill | cut)[..., None], (1 - alpha) * base + alpha * lay, base).astype(np.uint8)

    step = s.pitch / subdiv
    cx = s.cx - s.rx0
    for i in range(int(-cx / step) - 1, int((s.W - cx) / step) + 2):
        X = int(round(cx + i * step))
        if 0 <= X < s.W:
            cv2.line(out, (X, 0), (X, s.H - 1), cfg.grid_line_color_bgr, 1)
    cy = s.row_of(s.datum)
    for j in range(int(-cy / step) - 1, int((s.H - cy) / step) + 2):
        Y = int(round(cy + j * step))
        if 0 <= Y < s.H:
            cv2.line(out, (0, Y), (s.W - 1, Y), cfg.grid_line_color_bgr, 1)
    return out


def qc_trace_overlay(s: Section) -> np.ndarray:
    """Debug view: red dots on traced existing-ground points, blue dots on
    traced proposed-design points, over the cleaned ROI."""
    vis = cv2.cvtColor(255 - s.roi * 255, cv2.COLOR_GRAY2BGR)
    for x, y in s.ground_px.items():
        cv2.circle(vis, (x, int(y)), 3, (220, 40, 40), -1)
    for x, y in s.design_px.items():
        cv2.circle(vis, (x, int(y)), 3, (40, 90, 230), -1)
    return vis
