"""
Orchestration for the vector-PDF track: auto-detect cross-section pages
across a full plan set, split multi-section pages, compute fill/cut area
per section by cropping and reusing the existing raster Section pipeline,
group stations into roads, and compute trapezoidal volume per road.

This is the "upload the whole plan set" workflow -- no explicit page list
from the caller. A page counts as a cross-section page exactly when
CrossSectionSplitter.split() finds at least one region on it; every other
page (cover sheets, notes, plan/profile sheets) is silently skipped. That
skip IS the auto-detection -- there is no separate classifier.

Vector track: gridline positions for stripping/calibration are read
directly from the PDF's own vector paths (extract_vector_gridlines) rather
than re-detected from the raster crop -- see section_splitter.py.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import cv2
import fitz

from ..config import PipelineConfig
from .section_splitter import (
    CrossSectionSplitter, CrossSectionRegion, extract_sheet_metadata, extract_vector_gridlines,
)
from .section import Section
from .area import cell_ledger, page_totals
from .visualize import colour_composite
from .road_grouping import StationEntry, group_into_roads, RoadGroup
from .volume import average_end_area_volume, RoadVolumeResult


@dataclass
class StationArea:
    """What volume.py needs (station_label, station_ft, fill_ft2, cut_ft2),
    plus the extra detail worth keeping around for display/debugging."""
    station_label: str
    station_ft: float
    fill_ft2: float
    cut_ft2: float
    region: CrossSectionRegion
    coloured_image_path: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class PlanSetResult:
    pages_scanned: int
    cross_section_pages: int
    stations: list[StationArea]        # in document order
    roads: list[RoadGroup]
    volumes: list[RoadVolumeResult]    # same order as roads
    skipped_regions: list[str]         # human-readable notes on regions Section couldn't calibrate
    timing: dict                        # wall-clock seconds per stage, to find real bottlenecks
                                         # rather than guess -- see process_plan_set


def _crop_region_to_image(page: fitz.Page, region: CrossSectionRegion,
                           out_path: str, zoom: float = 3.0, pad_pt: float = 6.0) -> tuple[float, float]:
    """Render just this region's Y-band (full page width) to a PNG at `zoom`x
    the PDF's native point resolution. Returns (y0, y1) -- the crop's actual
    rendered top/bottom edges, in PDF points -- so callers can convert other
    page-space coordinates (e.g. vector gridline positions) into this same
    crop's pixel space using the SAME bounds this function actually used.

    IMPORTANT: for every region after the first, region.y_top is literally
    the PREVIOUS region's own bottom axis line (CrossSectionSplitter uses
    consecutive axis rows as shared boundaries). Padding outward at the top
    would pull that neighboring gridline into the crop, right at the edge --
    detect_lattice then misreads it as this region's own topmost line and
    miscalibrates everything downstream. So the top is inset (moved DOWN,
    into this region, past the foreign line) while the bottom -- which IS
    this region's own real axis line -- gets a small outward pad instead,
    to make sure that real line doesn't get clipped."""
    pw = page.rect.width
    y0 = min(region.y_top + pad_pt, region.y_bottom - 1.0)
    y1 = min(page.rect.height, region.y_bottom + pad_pt)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=fitz.Rect(0, y0, pw, y1))
    pix.save(out_path)
    return y0, y1


def _to_pixel_bands(positions: dict, offset_pt: float, zoom: float) -> list[tuple[int, int]]:
    """Convert {position_in_pt: line_width_in_pt} into the (start, end) pixel
    bands strip_grid()/Section already expect, in this crop's pixel space.

    Drops any band that isn't fully non-negative: a negative start would be
    silently reinterpreted by Python as counting from the end of the array
    inside strip_grid()'s slicing, wiping out most of the image instead of
    one line. That should never happen once the caller passes the crop's own
    real (y0, y1) bounds to extract_vector_gridlines(), but this is cheap
    insurance against exactly that class of bug recurring."""
    bands = []
    for pos_pt, width_pt in positions.items():
        center = round((pos_pt - offset_pt) * zoom)
        half = max(1, round(width_pt / 2 * zoom))
        start, end = center - half, center + half
        if start < 0:
            continue
        bands.append((start, end))
    return sorted(bands)


def process_plan_set(
    pdf_path: str,
    cfg: PipelineConfig,
    work_dir: str = "work",
    out_dir: str | None = "outputs",
    zoom: float = 3.0,
) -> PlanSetResult:
    # Absolute elevation values aren't reported by this workflow, and area/
    # volume math never depends on datum (see PipelineConfig.skip_ocr_datum) --
    # so always skip the expensive per-region OCR here regardless of what the
    # caller's cfg says, rather than relying on every caller to remember to
    # set the flag themselves.
    from dataclasses import replace
    cfg = replace(cfg, skip_ocr_datum=True)

    os.makedirs(work_dir, exist_ok=True)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    splitter = CrossSectionSplitter()
    doc = fitz.open(pdf_path)
    pages_scanned = len(doc)

    entries: list[StationEntry] = []
    stations: list[StationArea] = []
    skipped_regions: list[str] = []
    cross_section_pages = 0

    t_classify = t_crop = t_section = t_render = 0.0
    stage_totals: dict[str, float] = {}
    t_start = time.time()

    for page_index in range(pages_scanned):
        page_number = page_index + 1
        page = doc[page_index]

        t0 = time.time()
        regions = splitter.split(page, page_number)
        t_classify += time.time() - t0

        if not regions:
            continue
        cross_section_pages += 1
        sheet_meta = extract_sheet_metadata(splitter._get_spans(page))

        for i, region in enumerate(regions):
            crop_path = os.path.join(work_dir, f"page{page_number:03d}_region{i}.png")

            t0 = time.time()
            y0, y1 = _crop_region_to_image(page, region, crop_path, zoom=zoom)
            t_crop += time.time() - t0

            # Vector track only: read exact gridline positions from the PDF's
            # own drawing paths instead of leaving Section to re-detect them
            # from the raster crop. Falls back to raster detection
            # (known_gridlines=None) if a page's vector geometry comes back empty.
            #
            # IMPORTANT: search inside (y0, y1) -- the crop's ACTUAL rendered
            # bounds returned above -- not region.y_top/y_bottom. Those differ
            # (the crop insets its top edge past the neighboring region's
            # boundary line), and a line found outside the real crop produces
            # a negative/overflowing pixel band that would corrupt the image.
            h_rows, v_cols = extract_vector_gridlines(page, y0, y1)
            H_known = _to_pixel_bands(h_rows, offset_pt=y0, zoom=zoom)
            V_known = _to_pixel_bands(v_cols, offset_pt=0.0, zoom=zoom)
            known_gridlines = (V_known, H_known) if H_known else None

            section_id = page_index * 10 + i  # internal id only -- NOT the real station
            t0 = time.time()
            try:
                section = Section(page=section_id, path=crop_path, cfg=cfg,
                                   known_gridlines=known_gridlines)
            except (ValueError, FileNotFoundError) as e:
                t_section += time.time() - t0
                skipped_regions.append(
                    f"page {page_number} region {i} ({region.station_label}): "
                    f"could not calibrate -- {e}"
                )
                continue
            for k, v in section.stage_timings.items():
                stage_totals[k] = stage_totals.get(k, 0.0) + v
            ledger = cell_ledger(section, cfg.subdiv, cfg.supersample)
            totals = page_totals(ledger, section_id)
            t_section += time.time() - t0

            t0 = time.time()
            coloured_path = None
            if out_dir:
                img = colour_composite(section, cfg)
                safe_label = region.station_label.replace("+", "_")
                coloured_path = os.path.join(out_dir, f"page{page_number:03d}_{safe_label}.png")
                cv2.imwrite(coloured_path, img)
            t_render += time.time() - t0

            area = StationArea(
                station_label=region.station_label, station_ft=region.station_ft,
                fill_ft2=float(totals["fill_ft2"]), cut_ft2=float(totals["cut_ft2"]),
                region=region, coloured_image_path=coloured_path,
            )
            stations.append(area)
            entries.append(StationEntry(
                station_label=region.station_label, station_ft=region.station_ft,
                page_number=page_number, ref=area,
                road_name=sheet_meta["road_name"], series_id=sheet_meta["series_id"],
            ))

    doc.close()
    t_total = time.time() - t_start

    roads = group_into_roads(entries)
    volumes = [
        average_end_area_volume([e.ref for e in road.entries], road_label=road.label)
        for road in roads
    ]

    timing = {
        "total_seconds": round(t_total, 1),
        "classification_seconds": round(t_classify, 1),
        "crop_render_seconds": round(t_crop, 1),
        "section_calibration_seconds": round(t_section, 1),
        "coloured_overlay_seconds": round(t_render, 1),
        "n_regions": len(stations),
        "avg_seconds_per_region": round(t_section / len(stations), 2) if stations else 0.0,
        "section_substages": {k: round(v, 1) for k, v in sorted(
            stage_totals.items(), key=lambda kv: -kv[1])},
    }
    print(f"[process_plan_set] {timing}")

    return PlanSetResult(
        pages_scanned=pages_scanned, cross_section_pages=cross_section_pages,
        stations=stations, roads=roads, volumes=volumes, skipped_regions=skipped_regions,
        timing=timing,
    )
