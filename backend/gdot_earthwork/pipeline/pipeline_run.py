"""
Orchestration layer -- the one place that wires stages 1-5 together into a
single call per page. This is the module a future API/UI backend should
import; it is deliberately the *only* place that touches the filesystem
for outputs, so a web handler can swap that out for in-memory bytes later
without touching pipeline internals.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable

import cv2
import pandas as pd

from ..config import PipelineConfig, get_config
from .io_extract import extract_pages, check_system_deps
from .section import Section
from .area import cell_ledger, page_totals
from .visualize import colour_composite


@dataclass
class PageResult:
    page: int
    section: Section
    ledger: pd.DataFrame
    totals: dict
    diagnostics: dict
    calibration: dict
    coloured_image_path: str | None = None
    warnings: list[str] = field(default_factory=list)


def process_page(
    page: int,
    image_path: str,
    cfg: PipelineConfig,
    out_dir: str | None = None,
) -> PageResult:
    """Run stages 2-5 on a single already-extracted page image."""
    warnings: list[str] = []
    section = Section(page, image_path, cfg)
    ledger = cell_ledger(section, cfg.subdiv, cfg.supersample)
    totals = page_totals(ledger, page)

    if section.max_gap_g > cfg.gap_warn_ft or section.max_gap_d > cfg.gap_warn_ft:
        warnings.append(
            f"page {page}: surface has an unsupported (interpolated-only) gap "
            f"wider than {cfg.gap_warn_ft} ft -- area over that span is a straight-line guess."
        )
    for t in section.trimmed:
        warnings.append(
            f"page {page}: trimmed {t['side']} tail {t['x_from']:+.1f}..{t['x_to']:+.1f} ft "
            f"({t['run_ft']} ft long, {t['depth_ft']} ft below existing) -- treated as a "
            f"buried service, not a graded surface."
        )

    coloured_path = None
    if out_dir is not None:
        os.makedirs(out_dir, exist_ok=True)
        img = colour_composite(section, cfg)
        coloured_path = os.path.join(out_dir, f"coloured_page{page:03d}.png")
        cv2.imwrite(coloured_path, img)
        ledger.to_csv(os.path.join(out_dir, f"cells_page{page:03d}.csv"), index=False)

    return PageResult(
        page=page,
        section=section,
        ledger=ledger,
        totals=totals,
        diagnostics=section.summary(),
        calibration=section.calibration_check(),
        coloured_image_path=coloured_path,
        warnings=warnings,
    )


def process_pdf(
    pdf_path: str,
    pages: Iterable[int],
    cfg: PipelineConfig | str = "19series",
    work_dir: str = "work",
    out_dir: str | None = "outputs",
) -> dict[int, PageResult]:
    """Run the full pipeline (extract -> calibrate -> trace -> area -> render)
    for every page in `pages`. Returns {page: PageResult}."""
    if isinstance(cfg, str):
        cfg = get_config(cfg)

    deps = check_system_deps()
    missing = [k for k, ok in deps.items() if not ok]
    if missing:
        raise RuntimeError(
            f"Missing required system binaries: {missing}. "
            f"Install poppler-utils (pdfimages, pdftoppm) and tesseract-ocr."
        )

    page_files = extract_pages(pdf_path, pages, work_dir)
    results: dict[int, PageResult] = {}
    for p, path in page_files.items():
        results[p] = process_page(p, path, cfg, out_dir=out_dir)
    return results


def totals_table(results: dict[int, PageResult]) -> pd.DataFrame:
    return pd.DataFrame([r.totals for r in results.values()]).set_index("page").round(3)
