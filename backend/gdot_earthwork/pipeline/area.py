"""
Stage 4 -- the grid-cell area method.

Rasterizes the fill/cut band between the traced ground and design curves
at a supersampled resolution, then bins that raster into grid cells
(default: one cell per 10 ft grid square) and sums pixel counts into a
per-cell fill/cut area ledger.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .section import Section


def between_mask(s: Section, ss: int = 1):
    """Binary rasters of the FILL and CUT regions, at `ss` x native resolution.
    Rows/cols are in supersampled ROI pixel space."""
    H, W = s.H * ss, s.W * ss
    cols = np.arange(W)
    G = np.interp(cols / ss, np.arange(s.W), s.G) * ss
    D = np.interp(cols / ss, np.arange(s.W), s.D) * ss
    ok = ~np.isnan(G) & ~np.isnan(D)
    rr = np.arange(H)[:, None]
    lo = np.where(ok, np.minimum(G, D), np.inf)
    hi = np.where(ok, np.maximum(G, D), -np.inf)
    band = (rr >= lo) & (rr < hi)
    fill = band & (D < G)
    cut = band & (D > G)
    return fill, cut


def cell_ledger(s: Section, subdiv: int, ss: int) -> pd.DataFrame:
    """Cut into grid cells, measure each, note it down."""
    fill, cut = between_mask(s, ss)
    px_ft2 = 1.0 / (s.ppf * ss) ** 2

    step_px = s.pitch / subdiv * ss
    cx_ss = (s.cx - s.rx0) * ss
    ci0 = int(np.floor((0 - cx_ss) / step_px))
    ci1 = int(np.ceil((fill.shape[1] - cx_ss) / step_px))
    cy_ss = (s.row_of(s.datum)) * ss
    rj0 = int(np.floor((0 - cy_ss) / step_px))
    rj1 = int(np.ceil((fill.shape[0] - cy_ss) / step_px))

    rows = []
    for i in range(ci0, ci1):
        x0p, x1p = cx_ss + i * step_px, cx_ss + (i + 1) * step_px
        c0, c1 = int(max(0, np.floor(x0p))), int(min(fill.shape[1], np.ceil(x1p)))
        if c1 <= c0:
            continue
        fcol, ccol = fill[:, c0:c1], cut[:, c0:c1]
        if not (fcol.any() or ccol.any()):
            continue
        for j in range(rj0, rj1):
            y0p, y1p = cy_ss + j * step_px, cy_ss + (j + 1) * step_px
            r0, r1 = int(max(0, np.floor(y0p))), int(min(fill.shape[0], np.ceil(y1p)))
            if r1 <= r0:
                continue
            nf = int(fcol[r0:r1].sum())
            nc = int(ccol[r0:r1].sum())
            if nf == 0 and nc == 0:
                continue
            rows.append(dict(
                page=s.page, cell_i=i, cell_j=j,
                x_from=round(s.x_ft(c0 / ss), 2), x_to=round(s.x_ft(c1 / ss), 2),
                elev_top=round(s.elev(r0 / ss), 2), elev_bot=round(s.elev(r1 / ss), 2),
                fill_ft2=nf * px_ft2, cut_ft2=nc * px_ft2,
            ))
    return pd.DataFrame(rows)


def page_totals(ledger: pd.DataFrame, page: int) -> dict:
    return dict(
        page=page, cells=len(ledger),
        fill_ft2=ledger.fill_ft2.sum() if len(ledger) else 0.0,
        cut_ft2=ledger.cut_ft2.sum() if len(ledger) else 0.0,
        net_ft2=(ledger.fill_ft2.sum() - ledger.cut_ft2.sum()) if len(ledger) else 0.0,
    )
