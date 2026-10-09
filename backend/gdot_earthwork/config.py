"""
Central configuration for the GDOT cross-section earthwork pipeline.

Every tunable that used to live as a bare global at the top of the notebook
lives here instead, as a dataclass. Nothing in this file does any work --
it only describes *how* the pipeline should behave, so a caller (CLI,
background job, future API handler) can override per-run without editing
source.

If another drawing series turns out to need different
grid pitch, ink threshold, or gutter geometry, that difference should be
expressed as a new Config instance / preset here -- not a new code path
inside the pipeline modules.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineConfig:
    # --- grid & calibration ---
    grid_ft: float = 10.0          # real-world size of one grid square
    ink_thresh: int = 200          # grayscale value below which a pixel counts as "ink"
    elev_label_gutter: int = 134   # px width of the elevation-label strip right of the plot

    # --- curve cleanup ---
    despike_win: int = 9
    despike_px: float = 4.0

    # --- buried-service (false cut) filtering ---
    buried_run_ft: float = 25.0
    buried_depth_ft: float = 3.5

    # --- gap handling ---
    gap_refine_ft: float = 3.0
    gap_tol_px: float = 7.0
    gap_warn_ft: float = 5.0

    # --- grid-cell area method ---
    subdiv: int = 1                # subdivisions per grid cell (1 = one cell per 10 ft square)
    supersample: int = 4           # rasterization supersample factor for area accuracy

    # --- performance ---
    skip_ocr_datum: bool = False   # if True, don't OCR the elevation gutter -- falls back to
                                    # a relative datum. Fill/cut area and volume are UNAFFECTED
                                    # (area.py operates on pixel-row positions, never on the
                                    # elevation-converted values that depend on datum), so this
                                    # is safe to enable whenever absolute elevation values don't
                                    # need to be reported. OCR datum recovery launches tesseract
                                    # as a subprocess up to 6x per gridline, so on a plan set with
                                    # hundreds of regions this is the dominant cost -- skipping it
                                    # is the single biggest lever for processing speed.

    # --- visualization ---
    fill_color_bgr: tuple[int, int, int] = (79, 158, 46)     # green
    cut_color_bgr: tuple[int, int, int] = (59, 59, 209)      # red
    grid_line_color_bgr: tuple[int, int, int] = (170, 170, 170)
    overlay_alpha: float = 0.55


# Named presets. Add one per drawing series once its geometry is confirmed
# to differ from the default (validated originally against 19-series sheets).
PRESETS: dict[str, PipelineConfig] = {
    "19series": PipelineConfig(),
}


def get_config(name: str = "19series") -> PipelineConfig:
    try:
        return PRESETS[name]
    except KeyError as e:
        raise KeyError(
            f"Unknown pipeline preset {name!r}. Known presets: {list(PRESETS)}"
        ) from e
