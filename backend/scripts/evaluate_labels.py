"""
Score the app against hand-coloured cut/fill takeoffs, per GDOT sheet series.

Each project in the data drop has the same cross-section sheets twice: a
clean copy (what the app reads) and a copy an estimator coloured by hand --
fill green/teal, cut red/pink. For every cross-section this script runs the
app's own pipeline on the clean copy, registers the coloured page onto it
(ORB features + RANSAC, then ECC refinement), and compares fill/cut area,
pixel overlap and average-end-area volume.

  19 series (construction staging cross-sections, drawing no. 19-xxxx):
      scanned pages with several sections each. Each section is cut into a
      strip -- from one offset axis to the next, the same layout as the
      pages of 19series.pdf -- and run through the scanned-sheet pipeline
      (/api/process: raster grid detection, 19series preset).
  23 series (earthwork cross-sections, 23-xxxx): clean copies are vector
      PDFs, run through the plan-set pipeline (/api/process_plan_set).

19series.pdf itself has no labels; it gets a reliability check instead
(does every page calibrate, read its datum, and produce an area).

Label areas use a scale the app does not compute: the sheet's axis
numbers (23 series, from the PDF text) or its labelled 10 ft grid measured
across the whole page (19 series). Pages with no colouring are skipped.

Usage (from backend/):
    python scripts/evaluate_labels.py --data ../data/EARTHWORK --sheets19 ../data/19series.pdf

Writes ../frontend/src/data/accuracy.json (read by the Accuracy page) and
example comparison images to ../frontend/public/accuracy/; every
per-station comparison image goes to --work (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gdot_earthwork.config import get_config  # noqa: E402
from gdot_earthwork.pipeline.area import between_mask, cell_ledger, page_totals  # noqa: E402
from gdot_earthwork.pipeline.grid_geometry import detect_lattice  # noqa: E402
from gdot_earthwork.pipeline.io_extract import extract_pages  # noqa: E402
from gdot_earthwork.pipeline.plan_set_run import _crop_region_to_image, _to_pixel_bands  # noqa: E402
from gdot_earthwork.pipeline.road_grouping import StationEntry, group_into_roads  # noqa: E402
from gdot_earthwork.pipeline.section import Section  # noqa: E402
from gdot_earthwork.pipeline.section_splitter import CrossSectionSplitter, extract_vector_gridlines  # noqa: E402
from gdot_earthwork.pipeline.volume import average_end_area_volume  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# (labeled scan, clean twin), relative to --data. Pairs are matched by the
# drawing number in the title block -- some file names are swapped (e.g.
# Mountain Ind Blvd "EARTHWORK -STAGE 1" is the coloured copy of "STAGE 2").
PAIRS_19 = [
    dict(id="sr136_s1", name="SR 136 Lookout Creek · Stage 1", drawing="19-0008",
         labeled="SR 136 LOOKOUT CREEK/SR 136 AT LOOKOUT CREEK - EARTHWORK -STAGE 1.pdf",
         unlabeled="SR 136 LOOKOUT CREEK/SR 136 AT LOOKOUT CREEK - STAGE 1.pdf"),
    dict(id="sr136_s2", name="SR 136 Lookout Creek · Stage 2", drawing="19-0027",
         labeled="SR 136 LOOKOUT CREEK/SR 136 AT LOOKOUT CREEK- EARTHWORK -STAGE 2.pdf",
         unlabeled="SR 136 LOOKOUT CREEK/SR 136 AT LOOKOUT CREEK - STAGE 2.pdf"),
    dict(id="mtn_0022", name="Mountain Ind Blvd · 19-0022", drawing="19-0022",
         labeled="MOUNTAIN IND BLVD/MOUNTAIN IND BLVD -EARTHWORK -STAGE 1.pdf",
         unlabeled="MOUNTAIN IND BLVD/MOUNTAIN IND BLVD - STAGE 2.pdf"),
    dict(id="mtn_0005", name="Mountain Ind Blvd · 19-0005", drawing="19-0005",
         labeled="MOUNTAIN IND BLVD/MOUNTAIN IND BLVD -EARTHWORK-STAGE 2.pdf",
         unlabeled="MOUNTAIN IND BLVD/MOUNTAIN IND BLVD - STAGE 1.pdf"),
    dict(id="rs_s2", name="River Side Road · Stage 2", drawing="19-1013",
         labeled="RIVER SIDE ROAD/RIVER SIDE ROAD - EARTHWORK -STAGE  2.pdf",
         unlabeled="RIVER SIDE ROAD/RIVER SIDE ROAD - STAGE 2.pdf"),
]

PAIRS_23 = [
    dict(id="perry", name="Perry Creek Rd (SR 61)",
         labeled="PERRY CREEK/PERRY CREEK RD- TAKEOFF EARTHWORK.pdf",
         unlabeled="PERRY CREEK/PERRY CREEK- EARTHWORK.pdf"),
    dict(id="sr332", name="SR 332",
         labeled="SR 332/SR 332  - MAINLINE.pdf",
         unlabeled="SR 332/SR-332 EARTHWORK.pdf"),
    dict(id="sr70", name="SR 70 (Fulton Industrial Blvd)",
         labeled="SR 70/SR 70 - CROSS SECTION.pdf",
         unlabeled="SR 70/SR 70- EARTHWORK.pdf"),
    dict(id="webb", name="Webb Creek",
         labeled="WEBB CREEK/WEEB CREEK - EARTHWORK.pdf",
         unlabeled="WEBB CREEK/WEBB CREEK- EARTHWORK.pdf"),
]

NOT_SCORED_19 = [
    dict(name="River Side Road · Stage 3 (19-2013)",
         reason="The coloured copy has 26 pages and the clean copy 6, so the pages can't be paired."),
    dict(name="19series.pdf",
         reason="No hand-coloured copy exists. It gets the reliability check above instead."),
]

NOT_SCORED_23 = [
    dict(name="SR 136 Lookout Creek, River Side Road, Mountain Ind Blvd, Lakeside Drive (mainline)",
         reason="Both copies are scans with several cross-sections per page; only the 19-series staging "
                "sheets of these projects were cut into strips and scored."),
    dict(name="Florence Rd, Hamilton Road",
         reason="Almost no colour on the takeoff copy, so there is nothing to score against."),
]

ZOOM_APP = 3.0      # the app renders each cross-section crop at 3x PDF points
ZOOM_LABEL = 2.5    # labeled scans are ~6280 px wide; 2.5x keeps full detail
MIN_PAGE_LABEL_PX = 1500
MIN_AREA_FT2 = 5.0  # % errors are only meaningful above a few square feet
MIN_TOTAL_FT2 = 50.0  # ... and a project total needs more than a sliver labelled


# ---------------------------------------------------------------- labels --
def render(page: fitz.Page, zoom: float, rgb: bool = False) -> np.ndarray:
    cs = fitz.csRGB if rgb else fitz.csGRAY
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=cs)
    shape = (pix.h, pix.w, 3) if rgb else (pix.h, pix.w)
    return np.frombuffer(pix.samples, np.uint8).reshape(shape).copy()


def label_masks(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fill (green/teal) and cut (red/pink) masks from a coloured takeoff.
    Orange (an estimator's traced design line on SR 332) is excluded by hue.
    A closing bridges the grid lines and text drawn over the colour."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    coloured = (s >= 35) & (v >= 120)
    fill = coloured & (h >= 60) & (h <= 95)
    cut = coloured & ((h <= 8) | (h >= 165))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    out = []
    for m in (fill, cut):
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, k)
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
        keep = np.zeros(n, bool)
        keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 40
        out.append(keep[lab])
    return out[0], out[1]


# ---------------------------------------------------------- registration --
def register(u_gray: np.ndarray, l_gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Affine map from app-render pixels to label-render pixels, and the ECC
    correlation of the final fit (1.0 = perfect)."""
    su, sl = 1500 / u_gray.shape[1], 1500 / l_gray.shape[1]
    us = cv2.resize(u_gray, None, fx=su, fy=su, interpolation=cv2.INTER_AREA)
    ls = cv2.resize(l_gray, None, fx=sl, fy=sl, interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(8000)
    ku, du = orb.detectAndCompute(255 - us, None)
    kl, dl = orb.detectAndCompute(255 - ls, None)
    if du is None or dl is None:
        raise RuntimeError("no features")
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(du, dl, k=2)
    good = [a for a, b in (p for p in pairs if len(p) == 2) if a.distance < 0.8 * b.distance]
    if len(good) < 50:
        raise RuntimeError(f"only {len(good)} feature matches")
    pu = np.float32([ku[g.queryIdx].pt for g in good])
    pl = np.float32([kl[g.trainIdx].pt for g in good])
    A, _ = cv2.estimateAffinePartial2D(pu, pl, method=cv2.RANSAC, ransacReprojThreshold=3, maxIters=5000)
    if A is None:
        raise RuntimeError("RANSAC failed")
    M = A.copy()
    M[:, :2] *= su
    M /= sl

    f = 0.5  # ECC refinement at half resolution on blurred ink
    ub = cv2.GaussianBlur(cv2.resize(255 - u_gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA), (5, 5), 0)
    lb = cv2.GaussianBlur(cv2.resize(255 - l_gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA), (5, 5), 0)
    Mh = M.copy()
    Mh[:, 2] *= f
    cc, W = cv2.findTransformECC(
        ub.astype(np.float32), lb.astype(np.float32), Mh.astype(np.float32), cv2.MOTION_AFFINE,
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6), None, 5)
    Mr = W.astype(np.float64)
    Mr[:, 2] /= f
    return Mr, float(cc)


def warp_to_app(mask: np.ndarray, M: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    return cv2.warpAffine(mask.astype(np.uint8), M, (shape[1], shape[0]),
                          flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0) > 0


# ----------------------------------------------------------- true scale --
def true_scale(spans, region, page_width: float, tol: float = 2.0) -> tuple[float, float] | None:
    """Points per foot (horizontal, vertical) read from the sheet's own axis
    numbers -- independent of the app's grid calibration, so label areas
    are in real square feet even where the app mis-calibrates."""
    xs, offs = [], []
    for y, x, txt, _ in spans:
        if abs(y - region.y_bottom) < tol and 0.1 * page_width < x < 0.95 * page_width:
            try:
                v = int(txt)
            except ValueError:
                continue
            if -200 <= v <= 200:
                xs.append(x)
                offs.append(v)
    if len(set(offs)) < 5:
        return None
    sx = float(np.polyfit(offs, xs, 1)[0])
    ys, els = [], []
    for y, x, txt, _ in spans:
        if x < 0.12 * page_width and region.y_top - 5 <= y <= region.y_bottom + 5:
            try:
                v = float(txt)
            except ValueError:
                continue
            if 100 < v < 9999:
                ys.append(y)
                els.append(v)
    sy = abs(float(np.polyfit(els, ys, 1)[0])) if len(set(els)) >= 2 else sx
    if not (0.5 < sy / sx < 2.0):  # implausible vertical fit -- assume 1:1 scales
        sy = sx
    return sx, sy


# --------------------------------------------------------------- scoring --
def iou(a: np.ndarray, b: np.ndarray) -> float | None:
    union = (a | b).sum()
    return None if union == 0 else float((a & b).sum() / union)


def comparison_image(section: Section, crop_gray: np.ndarray, pf, pc, lf, lc) -> np.ndarray:
    """Agreement view: green/red where app and label agree, amber where only
    the label has colour (missed), blue where only the app does (extra)."""
    roi = crop_gray[section.ry0:section.ry0 + section.H, section.rx0:section.rx0 + section.W]
    base = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR).astype(float)
    base = 255 - (255 - base) * 0.55
    lay = base.copy()
    colours = [
        (pf & lf, (85, 157, 31)), (pc & lc, (47, 65, 217)),
        ((lf | lc) & ~((pf & lf) | (pc & lc)), (0, 169, 242)),
        ((pf | pc) & ~(lf | lc), (255, 75, 47)),
    ]
    any_ = np.zeros(pf.shape, bool)
    for m, c in colours:
        lay[m] = c
        any_ |= m
    out = np.where(any_[..., None], 0.3 * base + 0.7 * lay, base).astype(np.uint8)
    cols = np.where(any_.any(0))[0]
    if len(cols):
        pad = 120
        a, b = max(0, cols[0] - pad), min(out.shape[1], cols[-1] + pad)
        if b - a < 1400:
            mid = (a + b) // 2
            a, b = max(0, mid - 700), min(out.shape[1], mid + 700)
        out = out[:, a:b]
    if out.shape[1] > 1100:
        out = cv2.resize(out, None, fx=1100 / out.shape[1], fy=1100 / out.shape[1], interpolation=cv2.INTER_AREA)
    return out


# ------------------------------------------------- 19 series (scanned) --
def page_gray(page: fitz.Page) -> np.ndarray:
    """The page at the resolution of its embedded scan -- what pdfimages
    hands the scanned-sheet pipeline."""
    im = max(page.get_images(full=True), key=lambda i: i[2] * i[3])
    return render(page, im[2] / page.rect.width)


def _strip_lines(ink: np.ndarray) -> np.ndarray:
    h = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (120, 1)))
    v = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 120)))
    return ink & ~(h | v)


def axis_rows(ink: np.ndarray, V, H) -> list[int]:
    """Rows with a number beside (almost) every vertical grid line, just above
    or below the line: the offset axis (-140 ... 140) under each section.
    Sheets differ in where those numbers sit, so both sides are checked."""
    txt = _strip_lines(ink)
    xs = np.array([(s + e) / 2 for s, e in V if e - s + 1 <= 5][1:-1])
    rows = []
    for s, e in H:
        best = 0.0
        for src, (a, b) in ((txt, (s - 55, s - 2)), (txt, (e + 2, e + 55)), (ink, (e + 4, e + 60))):
            n, _, st, cen = cv2.connectedComponentsWithStats(src[max(0, a):b], 8)
            cx = np.array([cen[k][0] for k in range(1, n) if 6 <= st[k, 3] <= 50 and st[k, 4] >= 8])
            if len(cx) and len(xs):
                best = max(best, float(np.mean([np.any(np.abs(cx - x) < 40) for x in xs])))
        if best >= 0.7:
            rows.append((s + e) // 2)
    return rows


def section_strips(gray: np.ndarray):
    """Cut a staging sheet into one strip per cross-section, from the axis row
    above to its own axis row, inside the sheet frame -- the layout of a
    19series.pdf page. Returns (strips, px per ft across, px per ft down)."""
    ink = (gray < 200).astype(np.uint8)
    V, H = detect_lattice(ink)
    thin_h = [(s + e) / 2 for s, e in H if e - s + 1 <= 5]
    thin_v = [(s + e) / 2 for s, e in V if e - s + 1 <= 5]
    if len(thin_h) < 3 or len(thin_v) < 3:
        return [], None, None
    pitch_y, pitch_x = float(np.median(np.diff(thin_h))), float(np.median(np.diff(thin_v)))
    rows = []
    for y in axis_rows(ink, V, H):
        if not rows or y - rows[-1] >= 2 * pitch_y:  # drop the title-block edge just under the last axis
            rows.append(y)
    frame = [(s, e) for s, e in V if e - s + 1 >= 6]
    x0 = frame[0][1] + 3 if frame else 0
    x1 = frame[-1][0] - 3 if len(frame) > 1 else gray.shape[1]
    strips = []
    for k, y in enumerate(rows):
        top = rows[k - 1] if k else y - (rows[1] - rows[0] if len(rows) > 1 else 5 * pitch_y)
        strips.append((max(0, int(top) - 3), int(y) + 6, x0, x1))
    # the 10 ft grid is labelled on both axes, so a grid square is 10 ft x 10 ft
    return strips, pitch_x / 10.0, pitch_y / 10.0


def ocr_station(strip: np.ndarray) -> tuple[str, float] | None:
    """The station label (e.g. 13+00) printed inside the plot at its right
    end. Only glyph-sized marks between 78% of the width and the right axis
    are kept -- not the elevation gutter, the axis numbers or curve dashes."""
    ink = (strip < 200).astype(np.uint8)
    V, _ = detect_lattice(ink)
    thin = [(s + e) / 2 for s, e in V if e - s + 1 <= 5]
    x1 = int(max(thin)) - 8 if thin else strip.shape[1]
    c = _strip_lines(ink)[:strip.shape[0] - 70, int(strip.shape[1] * 0.78):x1]
    n, lab, st, _ = cv2.connectedComponentsWithStats(c, 8)
    keep = np.zeros(n, bool)
    keep[1:] = (st[1:, 3] >= 20) & (st[1:, 3] <= 90)
    img = cv2.copyMakeBorder(255 - keep[lab].astype(np.uint8) * 255, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
    fd, f = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(f, img)
    try:
        out = subprocess.run(["tesseract", f, "stdout", "--psm", "11", "-c", "tessedit_char_whitelist=0123456789+."],
                             capture_output=True, text=True).stdout
    finally:
        os.unlink(f)
    m = re.search(r"(\d{1,3})\s*\+\s*(\d{2})", out)
    if not m:
        return None
    return f"{m.group(1)}+{m.group(2)}", int(m.group(1)) * 100 + int(m.group(2))


def _label(v: float) -> str:
    return f"{int(v // 100)}+{int(round(v % 100)):02d}"


def repair_stations(rows: list[dict]) -> None:
    """OCR can misread a digit (13+00 as 15+00) or read nothing. Stations step
    evenly, so a reading that breaks an otherwise even sequence -- or a gap
    between two consistent neighbours -- gets the value its neighbours imply,
    and is flagged."""
    from collections import Counter
    vals = [r["station_ft"] for r in rows]
    diffs = [abs(b - a) for a, b in zip(vals, vals[1:]) if a is not None and b is not None and b != a]
    if len(diffs) < 3:
        return
    step = Counter(round(d) for d in diffs).most_common(1)[0][0]
    for i in range(1, len(rows) - 1):
        a, r, b = rows[i - 1]["station_ft"], rows[i]["station_ft"], rows[i + 1]["station_ft"]
        if a is None or b is None or abs(abs(b - a) - 2 * step) >= 1:
            continue
        mid = (a + b) / 2
        if r is None or abs(r - mid) > step / 2:
            rows[i]["station_ft"], rows[i]["station"], rows[i]["station_fixed"] = mid, _label(mid), True


def score_station(section: Section, cfg, pf, pc, lf, lc, sx: float, sy: float) -> dict:
    """Area, overlap and pixel counts for one cross-section. Label pixels are
    converted with the true scale (sx, sy px/ft), never the app's."""
    totals = page_totals(cell_ledger(section, cfg.subdiv, cfg.supersample), section.page)
    px_ft2 = 1.0 / (sx * sy)
    return dict(
        label_fill=round(float(lf.sum() * px_ft2), 2), label_cut=round(float(lc.sum() * px_ft2), 2),
        app_fill=round(float(totals["fill_ft2"]), 2), app_cut=round(float(totals["cut_ft2"]), 2),
        iou_fill=iou(pf, lf), iou_cut=iou(pc, lc), iou_all=iou(pf | pc, lf | lc),
        scale_error_pct=round((section.ppf - sx) / sx * 100, 1),
        _px=dict(fill=(int((pf & lf).sum()), int((pf & ~lf).sum()), int((~pf & lf).sum())),
                 cut=(int((pc & lc).sum()), int((pc & ~lc).sum()), int((~pc & lc).sum()))),
    )


def score_raster_project(pair: dict, data: Path, work: Path, cfg) -> dict:
    labeled = fitz.open(data / pair["labeled"])
    clean = fitz.open(data / pair["unlabeled"])
    if len(labeled) != len(clean):
        raise ValueError(f"{pair['id']}: page counts differ ({len(labeled)} vs {len(clean)})")
    img_dir = work / pair["id"]
    img_dir.mkdir(parents=True, exist_ok=True)
    crop_path = str(work / "strip.png")

    stations, pages_labeled, align_failed, skipped, found = [], 0, [], [], 0
    for i in range(len(clean)):
        lrgb = render(labeled[i], ZOOM_LABEL, rgb=True)
        lfill, lcut = label_masks(lrgb)
        if lfill.sum() + lcut.sum() < MIN_PAGE_LABEL_PX:
            continue
        gray = page_gray(clean[i])
        strips, sx, sy = section_strips(gray)
        if not strips:
            skipped.append(f"page {i + 1}: no cross-section axis rows found")
            continue
        pages_labeled += 1
        found += len(strips)
        try:
            M, cc = register(gray, cv2.cvtColor(lrgb, cv2.COLOR_RGB2GRAY))
        except (RuntimeError, cv2.error) as e:
            align_failed.append(f"page {i + 1}: {e}")
            continue
        if cc < 0.9:
            align_failed.append(f"page {i + 1}: weak alignment (ECC {cc:.2f})")
            continue
        wfill, wcut = warp_to_app(lfill, M, gray.shape), warp_to_app(lcut, M, gray.shape)

        page_rows = []
        for k, (y0, y1, x0, x1) in enumerate(strips):
            strip = gray[y0:y1, x0:x1]
            cv2.imwrite(crop_path, strip)
            sta = ocr_station(strip)
            label = sta[0] if sta else f"p{i + 1}·{k + 1}"
            try:
                s = Section(page=i * 10 + k, path=crop_path, cfg=cfg)
            except (ValueError, FileNotFoundError, IndexError) as e:
                skipped.append(f"page {i + 1} section {k + 1} ({label}): {str(e).split(': ', 1)[-1] or type(e).__name__}")
                continue
            pf, pc = between_mask(s, 1)
            r0, c0 = y0 + s.ry0, x0 + s.rx0
            lf, lc = wfill[r0:r0 + s.H, c0:c0 + s.W], wcut[r0:r0 + s.H, c0:c0 + s.W]
            row = dict(station=label, station_ft=sta[1] if sta else None, page=i + 1,
                       **score_station(s, cfg, pf, pc, lf, lc, sx, sy))
            name = f"{pair['id']}_p{i + 1:02d}_s{k + 1}.jpg"
            cv2.imwrite(str(img_dir / name), comparison_image(s, strip, pf, pc, lf, lc), [cv2.IMWRITE_JPEG_QUALITY, 80])
            row["_image"] = str(img_dir / name)
            page_rows.append(row)
        # sheets print stations top-down in either direction; put each page in
        # increasing order using the majority of its readings, so one misread
        # digit can't reorder the page
        known = [r["station_ft"] for r in page_rows if r["station_ft"] is not None]
        steps = [b - a for a, b in zip(known, known[1:])]
        if steps and sum(d < 0 for d in steps) > len(steps) / 2:
            page_rows.reverse()
        stations += page_rows
        print(f"  {pair['id']} page {i + 1}: {len(stations)} stations so far", flush=True)

    repair_stations(stations)
    return dict(stations=stations, pages_total=len(clean), pages_labeled=pages_labeled,
                align_failed=align_failed, skipped=skipped, sections_found=found)


# --------------------------------------------- 19series.pdf reliability --
def reliability_19(pdf: Path, work: Path) -> dict:
    """No labels exist for 19series.pdf, so check what can be checked: on how
    many pages does the scanned-sheet pipeline (OCR datum on, exactly as
    /api/process runs it) calibrate, recover the elevation datum, and
    produce an area without warnings."""
    cfg = get_config("19series")
    n = len(fitz.open(pdf))
    paths = extract_pages(str(pdf), range(1, n + 1), str(work / "sheets19"))
    pages, failures = [], []
    for p, path in paths.items():
        try:
            s = Section(page=p, path=path, cfg=cfg)
        except Exception as e:  # noqa: BLE001 -- any failure is the finding
            failures.append(f"page {p}: {str(e).split(': ', 1)[-1] or type(e).__name__}")
            continue
        t = page_totals(cell_ledger(s, cfg.subdiv, cfg.supersample), p)
        cal = s.calibration_check()
        gap = max(s.max_gap_g, s.max_gap_d)
        pages.append(dict(
            page=p, fill=round(float(t["fill_ft2"]), 1), cut=round(float(t["cut_ft2"]), 1),
            squares_err=cal["squares_err"], ft_per_square=cal["ft_per_square"],
            datum_ocr=not s.datum_source.startswith("relative"),
            ocr_inliers=s.ocr_inliers, ocr_total=s.ocr_total,
            max_gap_ft=round(float(gap), 1), trimmed=len(s.trimmed),
        ))
        print(f"  19series.pdf page {p}: ok", flush=True)
    ok = len(pages)
    pct = lambda k: round(100 * k / ok, 1) if ok else None  # noqa: E731
    return dict(
        file=pdf.name, pages=n, processed=ok, failed=len(failures), failures=failures,
        calibrated_pct=pct(sum(1 for r in pages if r["squares_err"] < 0.02)),
        ten_ft_grid_pct=pct(sum(1 for r in pages if abs(r["ft_per_square"] - 10) < 0.2)),
        datum_ocr_pct=pct(sum(1 for r in pages if r["datum_ocr"])),
        gap_warning_pct=pct(sum(1 for r in pages if r["max_gap_ft"] > cfg.gap_warn_ft)),
        trimmed_pct=pct(sum(1 for r in pages if r["trimmed"])),
        total_fill_ft2=round(sum(r["fill"] for r in pages), 1),
        total_cut_ft2=round(sum(r["cut"] for r in pages), 1),
        page_rows=pages,
    )


def score_vector_project(pair: dict, data: Path, work: Path, cfg) -> dict:
    labeled = fitz.open(data / pair["labeled"])
    clean = fitz.open(data / pair["unlabeled"])
    if len(labeled) != len(clean):
        raise ValueError(f"{pair['id']}: page counts differ ({len(labeled)} vs {len(clean)})")
    splitter = CrossSectionSplitter()
    img_dir = work / pair["id"]
    img_dir.mkdir(parents=True, exist_ok=True)

    stations, pages_labeled, align_failed, skipped = [], 0, [], []
    for i in range(len(clean)):
        upage, lpage = clean[i], labeled[i]
        regions = splitter.split(upage, i + 1)
        if not regions:
            continue
        lrgb = render(lpage, ZOOM_LABEL, rgb=True)
        lfill, lcut = label_masks(lrgb)
        if lfill.sum() + lcut.sum() < MIN_PAGE_LABEL_PX:
            continue
        pages_labeled += 1
        ugray = render(upage, ZOOM_APP)
        try:
            M, cc = register(ugray, cv2.cvtColor(lrgb, cv2.COLOR_RGB2GRAY))
        except (RuntimeError, cv2.error) as e:
            align_failed.append(f"page {i + 1}: {e}")
            continue
        if cc < 0.9:
            align_failed.append(f"page {i + 1}: weak alignment (ECC {cc:.2f})")
            continue
        wfill, wcut = warp_to_app(lfill, M, ugray.shape), warp_to_app(lcut, M, ugray.shape)
        spans = splitter._get_spans(upage)

        for r, region in enumerate(regions):
            crop_path = str(work / "crop.png")
            y0, y1 = _crop_region_to_image(upage, region, crop_path, zoom=ZOOM_APP)
            h_rows, v_cols = extract_vector_gridlines(upage, y0, y1)
            H_known = _to_pixel_bands(h_rows, offset_pt=y0, zoom=ZOOM_APP)
            V_known = _to_pixel_bands(v_cols, offset_pt=0.0, zoom=ZOOM_APP)
            try:
                s = Section(page=i * 10 + r, path=crop_path, cfg=cfg,
                            known_gridlines=(V_known, H_known) if H_known else None)
            except (ValueError, FileNotFoundError) as e:
                skipped.append(f"page {i + 1} {region.station_label}: {str(e).split(': ', 1)[-1]}")
                continue
            pf, pc = between_mask(s, 1)

            top = math.floor(y0 * ZOOM_APP) + s.ry0
            lf = wfill[top:top + s.H, s.rx0:s.rx0 + s.W]
            lc = wcut[top:top + s.H, s.rx0:s.rx0 + s.W]
            if lf.shape != pf.shape:  # ROI ran off the page edge
                skipped.append(f"page {i + 1} {region.station_label}: crop outside page")
                continue
            scale = true_scale(spans, region, upage.rect.width)
            if scale is None:
                skipped.append(f"page {i + 1} {region.station_label}: axis numbers unreadable, no true scale")
                continue
            row = dict(station=region.station_label, station_ft=region.station_ft, page=i + 1,
                       **score_station(s, cfg, pf, pc, lf, lc, scale[0] * ZOOM_APP, scale[1] * ZOOM_APP))
            name = f"{pair['id']}_p{i + 1:02d}_{region.station_label.replace('+', '_').replace('.', '_')}.jpg"
            cv2.imwrite(str(img_dir / name), comparison_image(s, cv2.imread(crop_path, 0), pf, pc, lf, lc),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
            row["_image"] = str(img_dir / name)
            stations.append(row)
        print(f"  {pair['id']} page {i + 1}: {len(stations)} stations so far", flush=True)

    return dict(stations=stations, pages_total=len(clean), pages_labeled=pages_labeled,
                align_failed=align_failed, skipped=skipped,
                sections_found=len(stations) + len(skipped))


# --------------------------------------------------------------- summary --
def area_summary(rows: list[dict], key: str) -> dict:
    lab = np.array([r[f"label_{key}"] for r in rows])
    app = np.array([r[f"app_{key}"] for r in rows])
    big = lab >= MIN_AREA_FT2
    ape = np.abs(app[big] - lab[big]) / lab[big] if big.any() else np.array([])
    ious = [r[f"iou_{key}"] for r in rows if r[f"iou_{key}"] is not None]
    return dict(
        label_total=round(float(lab.sum()), 1), app_total=round(float(app.sum()), 1),
        # a % of almost nothing is noise: report it only once enough area is labelled
        total_error_pct=round(float((app.sum() - lab.sum()) / lab.sum() * 100), 1) if lab.sum() >= MIN_TOTAL_FT2 else None,
        mae_ft2=round(float(np.abs(app - lab).mean()), 1) if len(rows) else None,
        median_ape_pct=round(float(np.median(ape) * 100), 1) if len(ape) else None,
        within_10_pct=round(float((ape <= 0.10).mean() * 100), 1) if len(ape) else None,
        within_25_pct=round(float((ape <= 0.25).mean() * 100), 1) if len(ape) else None,
        mean_iou=round(float(np.mean(ious)), 3) if ious else None,
        n_measured=int(big.sum()),
        bias_ft2=round(float((app - lab).mean()), 1) if len(rows) else None,
        rmse_ft2=round(float(np.sqrt(((app - lab) ** 2).mean())), 1) if len(rows) else None,
        pearson_r=round(float(np.corrcoef(app, lab)[0, 1]), 3) if len(rows) > 2 and app.std() > 0 and lab.std() > 0 else None,
        **pixel_summary(rows, key),
    )


def pixel_summary(rows: list[dict], key: str) -> dict:
    """Pixel-level precision / recall / F1, pooled over all stations:
    precision = how much of what the app coloured the estimator also did,
    recall = how much of the estimator's colour the app found."""
    tp = sum(r["_px"][key][0] for r in rows)
    fp = sum(r["_px"][key][1] for r in rows)
    fn = sum(r["_px"][key][2] for r in rows)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    r3 = lambda v: None if v is None else round(v, 3)  # noqa: E731
    return dict(precision=r3(prec), recall=r3(rec), f1=r3(f1))


class _Area:
    def __init__(self, label, ft, fill, cut):
        self.station_label, self.station_ft, self.fill_ft2, self.cut_ft2 = label, ft, fill, cut


def road_volumes(rows: list[dict]) -> list[dict]:
    """Average-end-area volume per road from the app's and the label's areas
    over the same stations (stations whose label couldn't be read are left out)."""
    entries = [StationEntry(r["station"], r["station_ft"], r["page"], ref=r) for r in rows if r["station_ft"] is not None]
    out = []
    for g in group_into_roads(entries):
        rs = [e.ref for e in g.entries]
        vl = average_end_area_volume([_Area(r["station"], r["station_ft"], r["label_fill"], r["label_cut"]) for r in rs])
        va = average_end_area_volume([_Area(r["station"], r["station_ft"], r["app_fill"], r["app_cut"]) for r in rs])
        pct = lambda a, b: round((a - b) / b * 100, 1) if b > 0 else None  # noqa: E731
        if len(rs) < 2:
            continue
        out.append(dict(
            road=g.label, stations=len(rs), first=rs[0]["station"], last=rs[-1]["station"],
            label_fill_cy=round(vl.total_fill_cy, 1), app_fill_cy=round(va.total_fill_cy, 1),
            label_cut_cy=round(vl.total_cut_cy, 1), app_cut_cy=round(va.total_cut_cy, 1),
            fill_error_pct=pct(va.total_fill_cy, vl.total_fill_cy),
            cut_error_pct=pct(va.total_cut_cy, vl.total_cut_cy),
        ))
    return out


def pick_examples(rows: list[dict], n_worst: int = 2) -> list[dict]:
    """A best, a typical and the worst stations by overlap, among stations
    with a meaningful amount of labelled earthwork."""
    cand = [r for r in rows if r["label_fill"] + r["label_cut"] >= 20 and r["iou_all"] is not None]
    if not cand:
        return []
    cand.sort(key=lambda r: r["iou_all"], reverse=True)
    picks = [("Best", cand[0]), ("Typical", cand[len(cand) // 2])]
    picks += [("Worst", r) for r in cand[-n_worst:] if r is not cand[0] and r is not cand[len(cand) // 2]]
    return [dict(kind=k, station=r["station"], page=r["page"], iou=round(r["iou_all"], 3),
                 label_fill=r["label_fill"], app_fill=r["app_fill"], label_cut=r["label_cut"],
                 app_cut=r["app_cut"], _image=r["_image"]) for k, r in picks]


def summarize(rows: list[dict], found: int) -> dict:
    ious = [r["iou_all"] for r in rows if r["iou_all"] is not None]
    return dict(
        n_stations=len(rows), sections_found=found,
        scored_pct=round(100 * len(rows) / found, 1) if found else None,
        calibrated_pct=round(float(np.mean([abs(r["scale_error_pct"]) <= 2 for r in rows]) * 100), 1) if rows else None,
        iou_all=round(float(np.mean(ious)), 3) if ious else None,
        fill=area_summary(rows, "fill"), cut=area_summary(rows, "cut"),
    )


def run_series(sid: str, name: str, pipeline: str, pairs: list[dict], scorer, not_scored: list[dict],
               data: Path, work: Path, images: Path, only) -> dict:
    cfg = replace(get_config("19series"), skip_ocr_datum=True)  # datum never changes areas; see config.py
    projects, all_rows, found = [], [], 0
    for pair in pairs:
        if only and pair["id"] not in only:
            continue
        print(f"[{sid}/{pair['id']}] {pair['name']}", flush=True)
        res = scorer(pair, data, work, cfg)
        rows = res["stations"]
        if not rows:
            not_scored = not_scored + [dict(name=pair["name"], reason="No cross-section on a coloured page could be scored: "
                                            + "; ".join((res["skipped"] + res["align_failed"])[:2] or ["no coloured pages"]))]
            continue
        all_rows += rows
        found += res["sections_found"]
        examples = pick_examples(rows)
        for ex in examples:
            dst = images / Path(ex["_image"]).name
            dst.write_bytes(Path(ex["_image"]).read_bytes())
            ex["image"] = f"accuracy/{dst.name}"
        summary = summarize(rows, res["sections_found"])
        for r in rows + examples:
            r.pop("_image", None)
        projects.append(dict(
            id=pair["id"], name=pair["name"], drawing=pair.get("drawing"),
            files=dict(labeled=pair["labeled"], unlabeled=pair["unlabeled"]),
            pages_total=res["pages_total"], pages_labeled=res["pages_labeled"],
            align_failed=res["align_failed"], skipped=res["skipped"],
            **summary, roads=road_volumes(rows), examples=examples, stations=rows,
        ))
    overall = summarize(all_rows, found)
    for p in projects:
        for r in p["stations"]:
            r.pop("_px", None)
    return dict(id=sid, name=name, pipeline=pipeline, overall=overall, projects=projects, not_scored=not_scored)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", required=True, help="Folder holding the EARTHWORK project folders")
    ap.add_argument("--sheets19", help="19series.pdf, for the reliability check (default: next to --data)")
    ap.add_argument("--series", nargs="*", default=["19", "23"], help="Series to score (default: 19 23)")
    ap.add_argument("--out", default=str(ROOT / "frontend/src/data/accuracy.json"))
    ap.add_argument("--images", default=str(ROOT / "frontend/public/accuracy"))
    ap.add_argument("--work", default=str(ROOT / "backend/local_results/accuracy"))
    ap.add_argument("--only", nargs="*", help="Project ids to run (default: all)")
    args = ap.parse_args()

    data, work, images = Path(args.data), Path(args.work), Path(args.images)
    work.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    series = []
    if "19" in args.series:
        s19 = run_series("19", "19 series", "Scanned sheets (/api/process), one strip per cross-section",
                         PAIRS_19, score_raster_project, NOT_SCORED_19, data, work, images, args.only)
        sheets19 = Path(args.sheets19) if args.sheets19 else data.parent / "19series.pdf"
        if sheets19.exists() and not args.only:
            print("[19/reliability] 19series.pdf", flush=True)
            s19["reliability"] = reliability_19(sheets19, work)
        series.append(s19)
    if "23" in args.series:
        series.append(run_series("23", "23 series", "Full plan set (/api/process_plan_set), vector PDFs",
                                 PAIRS_23, score_vector_project, NOT_SCORED_23, data, work, images, args.only))

    report = dict(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        runtime_s=round(time.time() - t0, 1),
        min_area_ft2=MIN_AREA_FT2,
        series=series,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    for s_ in series:
        print(f"== {s_['name']}:", json.dumps(s_["overall"]))
        for p in s_["projects"]:
            print(f"   {p['id']}: stations {p['stations'].__len__()} iou {p['iou_all']} "
                  f"fill {p['fill']['total_error_pct']}% cut {p['cut']['total_error_pct']}%")
        if "reliability" in s_:
            print("   reliability:", {k: v for k, v in s_["reliability"].items() if k not in ("page_rows", "failures")})
    print(f"wrote {args.out} in {report['runtime_s']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
