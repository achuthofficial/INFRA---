"""
Locates cross-section regions on a page of a SCANNED/raster PDF (no real
text layer) -- the scanned-sheet equivalent of section_splitter.py's
CrossSectionSplitter, which only works when real PDF text is present.

Since there's no text to read station labels or axis calibration from,
this works entirely off image structure:
  1. detect_lattice() already finds every horizontal gridline on the
     whole page. CLUSTER those lines by gap size: a small gap is just
     the next gridline of the SAME cross-section's own grid pitch; a
     gap much bigger than that is the margin between two stacked
     cross-sections.
  2. OCR the station label from a small crop near the sheet's right
     margin, where GDOT prints it for each cross-section -- same NNN+NN
     pattern the vector track reads from real text, just via tesseract
     instead.

Returns the SAME CrossSectionRegion shape section_splitter.py does, so it
plugs into the same downstream orchestration (crop -> Section -> road
grouping -> volume) without any other code needing to change.

NOT YET VALIDATED against a real scanned plan set -- only against a
synthetic page built to match the layout in the one real screenshot seen
so far (3 stacked sections, station label at the right margin). Scan
quality, exact label position, and label format can all vary in practice;
treat the tunables below as starting points to adjust once run against
real files.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

import cv2
import numpy as np

from .grid_geometry import detect_lattice
from .section_splitter import CrossSectionRegion


def cluster_lattice_rows(H_: list[tuple[int, int]], gap_multiplier: float = 1.6) -> list[list[tuple[int, int]]]:
    """Group horizontal lattice lines into separate cross-section bands.

    A gap between consecutive lines much bigger than the surrounding
    (normal grid-pitch) gaps marks a boundary between two stacked
    cross-sections, not just the next gridline of the same one.

    Uses the MODE of the gaps as the pitch baseline, not the median or a
    fixed value -- same reasoning as the interval-anomaly fix in
    volume.py: with only a couple of (larger) between-section gaps mixed
    into many equal within-section gaps, the mode robustly finds the true
    repeating pitch regardless of how many sections are stacked or how
    much bigger the boundary gap happens to be."""
    if len(H_) < 2:
        return [H_] if H_ else []
    from collections import Counter
    mids = [(s + e) / 2 for s, e in H_]
    gaps = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
    typical = Counter(round(g) for g in gaps).most_common(1)[0][0]
    groups: list[list[tuple[int, int]]] = [[H_[0]]]
    for i, gap in enumerate(gaps):
        if gap > gap_multiplier * typical:
            groups.append([])
        groups[-1].append(H_[i + 1])
    return [g for g in groups if len(g) >= 2]  # need >=2 lines to form a usable grid


def ocr_station_label(gray: np.ndarray, y0: int, y1: int, page_width: int,
                       right_margin_fraction: float = 0.80) -> tuple[str, float] | None:
    """OCR a small strip near the right margin for a NNN+NN station label."""
    if not _has_tesseract():
        return None
    x0 = int(page_width * right_margin_fraction)
    crop = gray[max(0, y0 - 10):min(gray.shape[0], y1 + 10), x0:page_width]
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    f = tempfile.mktemp(suffix=".png")
    cv2.imwrite(f, crop)
    try:
        out = subprocess.run(
            ["tesseract", f, "stdout", "--psm", "6",
             "-c", "tessedit_char_whitelist=0123456789+"],
            capture_output=True, text=True,
        )
    finally:
        os.unlink(f)
    for line in out.stdout.splitlines():
        m = re.search(r"(\d+)\+(\d{2})", line.strip())
        if m:
            label = f"{m.group(1)}+{m.group(2)}"
            station_ft = int(m.group(1)) * 100 + int(m.group(2))
            return label, station_ft
    return None


def _has_tesseract() -> bool:
    import shutil
    return shutil.which("tesseract") is not None


class RasterCrossSectionSplitter:
    """Raster-page equivalent of CrossSectionSplitter, for scanned PDFs
    with no text layer. Requires tesseract for station-label OCR."""

    def __init__(self, ink_thresh: int = 200, gap_multiplier: float = 1.6,
                 right_margin_fraction: float = 0.80):
        self.ink_thresh = ink_thresh
        self.gap_multiplier = gap_multiplier
        self.right_margin_fraction = right_margin_fraction

    def split(self, gray: np.ndarray, page_number: int) -> list[CrossSectionRegion]:
        """gray: full-page grayscale raster array (e.g. from
        page.get_pixmap() converted to a numpy array -- render the whole
        page once, this does not need per-region PDF re-rendering the way
        the vector track's cropping does, since there's nothing vector to
        re-render)."""
        ink = (gray < self.ink_thresh).astype(np.uint8)
        _, H_ = detect_lattice(ink)
        if len(H_) < 2:
            return []
        groups = cluster_lattice_rows(H_, self.gap_multiplier)
        if not groups:
            return []

        H, W = gray.shape
        regions = []
        for group in groups:
            y_top = max(0, group[0][0] - 40)
            y_bottom = min(H, group[-1][1] + 60)
            sta = ocr_station_label(gray, group[0][0], group[-1][1], W,
                                     self.right_margin_fraction)
            if sta is None:
                continue
            label, station_ft = sta
            regions.append(CrossSectionRegion(
                station_label=label, station_ft=station_ft,
                y_top=float(y_top), y_bottom=float(y_bottom),
                page_number=page_number,
            ))
        regions.sort(key=lambda r: r.station_ft)
        return regions
