"""
Score the plan-set pipeline against hand-coloured cut/fill takeoffs.

Each project in the data drop has the same cross-section sheets twice: a
clean vector PDF (what the app reads) and a scanned copy an estimator
coloured by hand -- fill green/teal, cut red/pink. This script:

  1. runs the app's own plan-set pipeline (same splitter, crop, Section and
     cell-ledger code as /api/process_plan_set) on the clean PDF;
  2. renders the coloured page, extracts the green / red label masks and
     registers that page onto the clean one (ORB features + RANSAC, then
     ECC refinement -- the two PDFs have different page sizes);
  3. compares, inside each cross-section's measured area, the app's fill /
     cut against the label: area in ft2, overlap (IoU), and average-end-area
     volume per road from both sets of areas.

Pages with no colouring at all are not scored (estimators only coloured
some sheets). Areas the estimator coloured that the app does not measure by
design -- notably pavement-structure boxes under the template, which they
mark as cut -- show up as "missed" cut; read the per-project notes.

Usage (from backend/):
    python scripts/evaluate_labels.py --data ../data/EARTHWORK

Writes ../frontend/src/data/accuracy.json (read by the Accuracy page) and a
few example comparison images to ../frontend/public/accuracy/. All
per-station comparison images go to --work (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
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
from gdot_earthwork.pipeline.plan_set_run import _crop_region_to_image, _to_pixel_bands  # noqa: E402
from gdot_earthwork.pipeline.road_grouping import StationEntry, group_into_roads  # noqa: E402
from gdot_earthwork.pipeline.section import Section  # noqa: E402
from gdot_earthwork.pipeline.section_splitter import CrossSectionSplitter, extract_vector_gridlines  # noqa: E402
from gdot_earthwork.pipeline.volume import average_end_area_volume  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# (labeled scan, clean vector twin), relative to --data. Only pairs whose
# clean copy is a vector PDF can be scored: the app has no mode for scanned
# pages with several stacked cross-sections (see NOT_SCORED).
PAIRS = [
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

NOT_SCORED = [
    dict(name="SR 136 Lookout Creek, River Side Road, Mountain Ind Blvd, Lakeside Drive",
         reason="Both copies are scanned images with several cross-sections per page. The app "
                "reads scanned sheets one cross-section per page only, so these can't be run "
                "through it yet."),
    dict(name="Florence Rd, Hamilton Road",
         reason="Almost no colour on the takeoff copy, so there is nothing to score against."),
]

ZOOM_APP = 3.0      # the app renders each cross-section crop at 3x PDF points
ZOOM_LABEL = 2.5    # labeled scans are ~6280 px wide; 2.5x keeps full detail
MIN_PAGE_LABEL_PX = 1500
MIN_AREA_FT2 = 5.0  # % errors are only meaningful above a few square feet


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


def score_project(pair: dict, data: Path, work: Path, cfg) -> dict:
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
            totals = page_totals(cell_ledger(s, cfg.subdiv, cfg.supersample), s.page)
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
            sx, sy = scale[0] * ZOOM_APP, scale[1] * ZOOM_APP  # px per ft in this render
            px_ft2 = 1.0 / (sx * sy)
            row = dict(
                station=region.station_label, station_ft=region.station_ft, page=i + 1,
                label_fill=round(float(lf.sum() * px_ft2), 2), label_cut=round(float(lc.sum() * px_ft2), 2),
                app_fill=round(float(totals["fill_ft2"]), 2), app_cut=round(float(totals["cut_ft2"]), 2),
                iou_fill=iou(pf, lf), iou_cut=iou(pc, lc), iou_all=iou(pf | pc, lf | lc),
                scale_error_pct=round((s.ppf - sx) / sx * 100, 1),
            )
            name = f"{pair['id']}_p{i + 1:02d}_{region.station_label.replace('+', '_').replace('.', '_')}.jpg"
            cv2.imwrite(str(img_dir / name), comparison_image(s, cv2.imread(crop_path, 0), pf, pc, lf, lc),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
            row["_image"] = str(img_dir / name)
            stations.append(row)
        print(f"  {pair['id']} page {i + 1}: {len(stations)} stations so far", flush=True)

    return dict(stations=stations, pages_total=len(clean), pages_labeled=pages_labeled,
                align_failed=align_failed, skipped=skipped)


# --------------------------------------------------------------- summary --
def area_summary(rows: list[dict], key: str) -> dict:
    lab = np.array([r[f"label_{key}"] for r in rows])
    app = np.array([r[f"app_{key}"] for r in rows])
    big = lab >= MIN_AREA_FT2
    ape = np.abs(app[big] - lab[big]) / lab[big] if big.any() else np.array([])
    ious = [r[f"iou_{key}"] for r in rows if r[f"iou_{key}"] is not None]
    return dict(
        label_total=round(float(lab.sum()), 1), app_total=round(float(app.sum()), 1),
        total_error_pct=round(float((app.sum() - lab.sum()) / lab.sum() * 100), 1) if lab.sum() > 0 else None,
        mae_ft2=round(float(np.abs(app - lab).mean()), 1) if len(rows) else None,
        median_ape_pct=round(float(np.median(ape) * 100), 1) if len(ape) else None,
        within_10_pct=round(float((ape <= 0.10).mean() * 100), 1) if len(ape) else None,
        within_25_pct=round(float((ape <= 0.25).mean() * 100), 1) if len(ape) else None,
        mean_iou=round(float(np.mean(ious)), 3) if ious else None,
        n_measured=int(big.sum()),
    )


class _Area:
    def __init__(self, label, ft, fill, cut):
        self.station_label, self.station_ft, self.fill_ft2, self.cut_ft2 = label, ft, fill, cut


def road_volumes(rows: list[dict]) -> list[dict]:
    entries = [StationEntry(r["station"], r["station_ft"], r["page"], ref=r) for r in rows]
    out = []
    for g in group_into_roads(entries):
        rs = [e.ref for e in g.entries]
        vl = average_end_area_volume([_Area(r["station"], r["station_ft"], r["label_fill"], r["label_cut"]) for r in rs])
        va = average_end_area_volume([_Area(r["station"], r["station_ft"], r["app_fill"], r["app_cut"]) for r in rs])
        pct = lambda a, b: round((a - b) / b * 100, 1) if b > 0 else None  # noqa: E731
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", required=True, help="Folder holding the EARTHWORK project folders")
    ap.add_argument("--out", default=str(ROOT / "frontend/src/data/accuracy.json"))
    ap.add_argument("--images", default=str(ROOT / "frontend/public/accuracy"))
    ap.add_argument("--work", default=str(ROOT / "backend/local_results/accuracy"))
    ap.add_argument("--only", nargs="*", help="Project ids to run (default: all)")
    args = ap.parse_args()

    data, work, images = Path(args.data), Path(args.work), Path(args.images)
    work.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    cfg = replace(get_config("19series"), skip_ocr_datum=True)  # exactly what the plan-set endpoint uses

    projects, all_rows = [], []
    t0 = time.time()
    for pair in PAIRS:
        if args.only and pair["id"] not in args.only:
            continue
        print(f"[{pair['id']}] {pair['name']}", flush=True)
        res = score_project(pair, data, work, cfg)
        rows = res["stations"]
        all_rows += rows
        examples = pick_examples(rows)
        for ex in examples:
            dst = images / Path(ex["_image"]).name
            dst.write_bytes(Path(ex["_image"]).read_bytes())
            ex["image"] = f"accuracy/{dst.name}"
        for r in rows + examples:
            r.pop("_image", None)
        projects.append(dict(
            id=pair["id"], name=pair["name"],
            files=dict(labeled=pair["labeled"], unlabeled=pair["unlabeled"]),
            pages_total=res["pages_total"], pages_labeled=res["pages_labeled"],
            align_failed=res["align_failed"], skipped=res["skipped"],
            fill=area_summary(rows, "fill"), cut=area_summary(rows, "cut"),
            iou_all=round(float(np.mean([r["iou_all"] for r in rows if r["iou_all"] is not None])), 3) if rows else None,
            calibrated_pct=round(float(np.mean([abs(r["scale_error_pct"]) <= 2 for r in rows]) * 100), 1) if rows else None,
            roads=road_volumes(rows) if rows else [], examples=examples, stations=rows,
        ))

    report = dict(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        runtime_s=round(time.time() - t0, 1),
        min_area_ft2=MIN_AREA_FT2,
        overall=dict(stations=len(all_rows),
                     skipped=sum(len(p["skipped"]) + len(p["align_failed"]) for p in projects),
                     calibrated_pct=round(float(np.mean([abs(r["scale_error_pct"]) <= 2 for r in all_rows]) * 100), 1) if all_rows else None, fill=area_summary(all_rows, "fill"), cut=area_summary(all_rows, "cut"),
                     iou_all=round(float(np.mean([r["iou_all"] for r in all_rows if r["iou_all"] is not None])), 3) if all_rows else None),
        projects=projects,
        not_scored=NOT_SCORED,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps(report["overall"], indent=1))
    for p in projects:
        print(p["id"], "fill", p["fill"], "\n   cut", p["cut"], "\n   roads", p["roads"])
    print(f"wrote {args.out} in {report['runtime_s']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
