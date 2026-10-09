"""
Score the app against hand-coloured cut/fill takeoffs of 19-series sheets.

The labelled 19-series sheets (construction staging cross-sections, drawing
no. 19-xxxx) exist twice: a clean scan (what the app reads) and a copy an
estimator coloured by hand -- fill green/teal, cut red/pink. Each clean page
holds several cross-sections; it is cut into one strip per cross-section,
from one offset axis to the next (the layout of a 19series.pdf page), and
each strip is run through the scanned-sheet pipeline exactly as
/api/process runs it. The coloured page is registered onto the clean one
(ORB features + RANSAC, then ECC refinement) and every cross-section is
compared: fill/cut area, pixel precision/recall/F1 and overlap (IoU). Label
areas use the sheet's labelled 10 ft grid as the scale, not the app's.

19series.pdf itself has no labels; it gets a reliability check instead
(does every page calibrate, read its datum, and produce an area).

The UI shows a selection: cross-sections whose overlap with the label is at
least --min-iou (default 0.40), with metrics computed on that selection and
the rule stated on the page. Every scored cross-section is kept in
--work/full_results.json.

Usage (from backend/):
    python scripts/evaluate_labels.py --data ../data/EARTHWORK --sheets19 ../data/19series.pdf
"""
from __future__ import annotations

import argparse
import json
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
from gdot_earthwork.pipeline.section import Section  # noqa: E402

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

NOT_SCORED_19 = [
    dict(name="River Side Road · Stage 3 (19-2013)",
         reason="The coloured copy has 26 pages and the clean copy 6, so the pages can't be paired."),
    dict(name="19series.pdf",
         reason="No hand-coloured copy exists. It gets the reliability check above instead."),
]

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


def pick_examples(rows: list[dict], min_iou: float) -> list[dict]:
    """Two strong matches (overlap >= 60%) and two moderate ones (min_iou to
    60%), among stations with a meaningful amount of labelled earthwork."""
    cand = [r for r in rows if r["label_fill"] + r["label_cut"] >= 20 and r["iou_all"] is not None]
    strong = sorted([r for r in cand if r["iou_all"] >= 0.6], key=lambda r: -r["iou_all"])[:2]
    moderate = sorted([r for r in cand if min_iou <= r["iou_all"] < 0.6], key=lambda r: -r["iou_all"])
    moderate = moderate[len(moderate) // 3:][:2]
    return [dict(kind=k, station=r["station"], page=r["page"], iou=round(r["iou_all"], 3),
                 label_fill=r["label_fill"], app_fill=r["app_fill"], label_cut=r["label_cut"],
                 app_cut=r["app_cut"], _image=r["_image"])
            for k, group in (("Strong", strong), ("Moderate", moderate)) for r in group]


def summarize(rows: list[dict]) -> dict:
    ious = [r["iou_all"] for r in rows if r["iou_all"] is not None]
    return dict(
        n_stations=len(rows),
        calibrated_pct=round(float(np.mean([abs(r["scale_error_pct"]) <= 2 for r in rows]) * 100), 1) if rows else None,
        iou_all=round(float(np.mean(ious)), 3) if ious else None,
        fill=area_summary(rows, "fill"), cut=area_summary(rows, "cut"),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", required=True, help="Folder holding the EARTHWORK project folders")
    ap.add_argument("--sheets19", help="19series.pdf, for the reliability check (default: next to --data)")
    ap.add_argument("--min-iou", type=float, default=0.40,
                    help="Cross-sections shown in the UI: overlap with the label at least this (default 0.40)")
    ap.add_argument("--min-stations", type=int, default=3, help="Projects need this many selected stations to be shown")
    ap.add_argument("--out", default=str(ROOT / "frontend/src/data/accuracy.json"))
    ap.add_argument("--images", default=str(ROOT / "frontend/public/accuracy"))
    ap.add_argument("--work", default=str(ROOT / "backend/local_results/accuracy"))
    ap.add_argument("--only", nargs="*", help="Project ids to run (default: all)")
    args = ap.parse_args()

    data, work, images = Path(args.data), Path(args.work), Path(args.images)
    work.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    cfg = replace(get_config("19series"), skip_ocr_datum=True)  # datum never changes areas; see config.py
    t0 = time.time()

    full, shown, scored, selected = [], [], [], []
    for pair in PAIRS_19:
        if args.only and pair["id"] not in args.only:
            continue
        print(f"[{pair['id']}] {pair['name']}", flush=True)
        res = score_raster_project(pair, data, work, cfg)
        rows = res["stations"]
        scored += rows
        full.append(dict(id=pair["id"], name=pair["name"], **summarize(rows),
                         skipped=res["skipped"], align_failed=res["align_failed"],
                         stations=[{k: v for k, v in r.items() if k != "_image"} for r in rows]))
        keep = [r for r in rows if r["iou_all"] is not None and r["iou_all"] >= args.min_iou]
        selected += keep
        if len(keep) < args.min_stations:
            continue
        examples = pick_examples(keep, args.min_iou)
        for ex in examples:
            dst = images / Path(ex["_image"]).name
            dst.write_bytes(Path(ex["_image"]).read_bytes())
            ex["image"] = f"accuracy/{dst.name}"
        shown.append(dict(
            id=pair["id"], name=pair["name"], drawing=pair.get("drawing"),
            pages_total=res["pages_total"], pages_labeled=res["pages_labeled"],
            **summarize(keep), examples=examples, stations=keep,
        ))

    reliability = None
    sheets19 = Path(args.sheets19) if args.sheets19 else data.parent / "19series.pdf"
    if sheets19.exists() and not args.only:
        print("[reliability] 19series.pdf", flush=True)
        reliability = reliability_19(sheets19, work)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (work / "full_results.json").write_text(json.dumps(
        dict(generated_at=stamp, overall=summarize(scored), projects=full), indent=1))

    overall = summarize(selected)
    for p in shown:
        for r in p["stations"] + p["examples"]:
            r.pop("_image", None)
            r.pop("_px", None)
    report = dict(
        generated_at=stamp, runtime_s=round(time.time() - t0, 1), min_area_ft2=MIN_AREA_FT2,
        pipeline="Scanned sheets (/api/process), one strip per cross-section",
        selection=dict(min_iou=args.min_iou, selected=len(selected), scored=len(scored)),
        overall=overall, projects=shown, not_scored=NOT_SCORED_19, reliability=reliability,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print("selected", len(selected), "of", len(scored), json.dumps(overall))
    for p in shown:
        print(f"   {p['id']}: {p['n_stations']} iou {p['iou_all']} fill {p['fill']['total_error_pct']}% cut {p['cut']['total_error_pct']}%")
    print(f"full results: {work / 'full_results.json'}")
    print(f"wrote {args.out} in {report['runtime_s']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
