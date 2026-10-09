"""
Stage 3 -- clean the region-of-interest ink mask before curve tracing:
drop annotation glyphs, then split what's left into the dashed existing-
ground line and the solid proposed-design line.
"""
from __future__ import annotations

import cv2
import numpy as np


def denoise(roi: np.ndarray) -> tuple[np.ndarray, int]:
    """Drop annotation glyphs, traffic arrows and survey specks. Discriminator is
    BOX FILL RATIO: a digit fills ~0.3-0.6 of its bounding box, a 2 px line
    through the same box fills < 0.15.

    Vectorized: the original did `keep[lab == k] = 1` inside a Python loop
    over every connected component -- each `lab == k` rescans the whole
    image, so cost is O(components x image size). A real drawing can have
    hundreds of small components (every digit, dimension tick, hatch mark),
    confirmed as one of the two dominant per-region costs on real GDOT plan
    sets. This builds one boolean keep/drop table indexed by label (cheap,
    one entry per component) and applies it to the whole image in a single
    vectorized indexing op instead of one pass per component."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(roi, 8)
    drop = np.zeros(n, dtype=bool)
    dropped = 0
    for k in range(1, n):
        x, y, w, h, a = st[k]
        f = a / (w * h)
        if (8 <= w <= 70 and 10 <= h <= 55 and f >= 0.30) \
           or (a > 700 and f >= 0.35) or (a <= 12 and w <= 7 and h <= 7):
            drop[k] = True
            dropped += 1
    keep = np.where(drop[lab], 0, roi).astype(roi.dtype)
    return keep, dropped


def split_dash_solid(mask: np.ndarray):
    """Existing ground is DASHED, the proposed template is SOLID. Estimate the
    dash length from the component-width distribution and cut at 3x the median,
    so the threshold adapts to scan resolution instead of being hard-coded.

    Vectorized for the same reason as denoise() above -- see its docstring."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    ws = st[1:, cv2.CC_STAT_WIDTH] if n > 1 else np.array([])
    dash_w = float(np.median(ws)) if len(ws) else 12.0
    thr = max(40.0, 3.0 * dash_w)
    is_solid = np.zeros(n, dtype=bool)
    if n > 1:
        hs = st[1:, cv2.CC_STAT_HEIGHT]
        is_solid[1:] = np.maximum(ws, hs) >= thr
    solid_px = is_solid[lab]
    solid = np.where(solid_px, mask, 0).astype(mask.dtype)
    dash = np.where(solid_px, 0, mask).astype(mask.dtype)
    return dash, solid, thr, dash_w
