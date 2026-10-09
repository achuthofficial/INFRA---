"""
Section -- everything measured off one cross-section sheet, in engineering
units. This is the per-page orchestrator: it runs grid calibration, OCR
datum recovery, denoising, dash/solid separation, and curve tracing, and
exposes the results (ground/design elevation arrays, overlap mask,
diagnostics) that the area and visualization stages consume.
"""
from __future__ import annotations

import time

import numpy as np
import cv2

from ..config import PipelineConfig
from .grid_geometry import detect_lattice, plot_axes, strip_grid
from .ocr_datum import read_elev_labels, fit_datum
from .preprocess import denoise, split_dash_solid
from .curve_trace import (
    candidates, best_path, snap_top, despike, densify,
    trim_buried_tail, refine_gaps, interp_spans,
)


class Section:
    def __init__(self, page: int, path: str, cfg: PipelineConfig, known_gridlines=None):
        self.page, self.path, self.cfg = page, path, cfg
        self.stage_timings: dict[str, float] = {}
        _t = time.time()

        def _mark(name: str):
            nonlocal _t
            now = time.time()
            self.stage_timings[name] = now - _t
            _t = now

        g = cv2.imread(path, 0)
        if g is None:
            raise FileNotFoundError(f"Could not read image for page {page} at {path!r}")
        self.gray = g
        ink = (g < cfg.ink_thresh).astype(np.uint8)
        self.ink = ink
        _mark("imread_threshold")

        if known_gridlines is not None:
            V, H_ = known_gridlines
        else:
            V, H_ = detect_lattice(ink)
        if len(H_) < 2:
            raise ValueError(
                f"page {page}: fewer than 2 horizontal grid lines detected -- "
                f"this sheet's layout may not match the expected format."
            )
        lat = [(s + e) / 2 for s, e in H_]
        self.pitch = float(np.median(np.diff(lat)))
        self.lat_rows = lat
        self.Lx, self.Rx = plot_axes(ink, V, H_[0][1] + 3, H_[-1][0] - 3, self.pitch)
        _mark("lattice_and_axes")

        self.span_ft = round((self.Rx - self.Lx) / (self.pitch / cfg.grid_ft) / 10) * 10
        self.ppf = (self.Rx - self.Lx) / self.span_ft
        self.cx = (self.Lx + self.Rx) / 2.0

        if cfg.skip_ocr_datum:
            pool, ni, nt = [], 0, 0
            C = None
        else:
            pool = read_elev_labels(ink, V, H_, self.Rx, lat, cfg.elev_label_gutter)
            C, ni, nt = fit_datum(pool, lat, self.pitch, cfg.grid_ft)
        self.ocr_inliers, self.ocr_total = ni, nt
        if C is None:
            C = self.pitch * len(lat) / self.ppf
            self.datum_source = "relative (no datum recovered - elevations are not AMSL)"
        else:
            self.datum_source = f"OCR consensus {ni}/{nt}"
        self.datum = C
        _mark("ocr_datum")

        clean = strip_grid(ink, V, H_)
        _mark("strip_grid")
        top = H_[0][0] - 1 if H_[0][0] > 10 else H_[0][1] + 2
        bot = H_[-1][0] - 42
        self.rx0, self.ry0 = int(self.Lx) + 16, max(0, top)
        roi = clean[self.ry0:bot, self.rx0:int(self.Rx) - 16]
        self.roi, self.dropped = denoise(roi)
        _mark("denoise")
        self.dash, self.solid, self.dash_thr, self.dash_w = split_dash_solid(self.roi)
        _mark("dash_solid_split")

        self.H, self.W = self.roi.shape
        self.ground_px = best_path(candidates(self.dash))
        _mark("ground_trace")
        self.design_px = snap_top(self.solid, best_path(candidates(self.solid)))
        _mark("design_trace")
        self.ground_px, self.n_refined_g = refine_gaps(
            self.ground_px, self.roi, self.ppf, cfg.gap_refine_ft, cfg.gap_tol_px)
        self.design_px, self.n_refined_d = refine_gaps(
            self.design_px, self.solid, self.ppf, cfg.gap_refine_ft, cfg.gap_tol_px)
        _mark("refine_gaps")
        self.g_interp, self.max_gap_g = interp_spans(self.ground_px, self.W, self.ppf, cfg.gap_warn_ft)
        self.d_interp, self.max_gap_d = interp_spans(self.design_px, self.W, self.ppf, cfg.gap_warn_ft)
        _mark("interp_spans")
        self.G, self.n_spike_g = despike(densify(self.ground_px, self.W), cfg.despike_win, cfg.despike_px)
        self.D, self.n_spike_d = despike(densify(self.design_px, self.W), cfg.despike_win, cfg.despike_px)
        _mark("despike_densify")
        self.D, self.trimmed = trim_buried_tail(
            self.x_ft(np.arange(self.W)), self.G, self.D, self.ppf,
            cfg.buried_run_ft, cfg.buried_depth_ft)
        _mark("trim_buried_tail")

    # -- coordinate conversions --
    def x_ft(self, col):
        return (self.rx0 + np.asarray(col, float) - self.cx) / self.ppf

    def col_of(self, xft):
        return np.asarray(xft, float) * self.ppf + self.cx - self.rx0

    def elev(self, row):
        return self.datum - (self.ry0 + np.asarray(row, float)) / self.ppf

    def row_of(self, e):
        return (self.datum - np.asarray(e, float)) * self.ppf - self.ry0

    @property
    def x(self):
        return self.x_ft(np.arange(self.W))

    @property
    def ground(self):
        return self.elev(self.G)

    @property
    def design(self):
        return self.elev(self.D)

    @property
    def unsupported(self):
        """Columns where either surface is a guess across a wide gap."""
        return self.g_interp | self.d_interp

    @property
    def overlap(self):
        """Columns where BOTH surfaces exist -- the only place an area is defined."""
        return ~np.isnan(self.G) & ~np.isnan(self.D)

    def summary(self) -> dict:
        ov = self.overlap
        xs = self.x[ov]
        return dict(
            page=self.page, px_per_ft=round(self.ppf, 4),
            span_ft=self.span_ft, datum=round(self.datum, 2),
            datum_src=self.datum_source,
            ground_from=round(self.x[~np.isnan(self.G)].min(), 1),
            ground_to=round(self.x[~np.isnan(self.G)].max(), 1),
            design_from=round(xs.min(), 2) if ov.any() else None,
            design_to=round(xs.max(), 2) if ov.any() else None,
            glyphs_removed=self.dropped,
            spikes_g=self.n_spike_g, spikes_d=self.n_spike_d,
            max_gap_g_ft=round(self.max_gap_g, 1), max_gap_d_ft=round(self.max_gap_d, 1),
            trimmed=len(self.trimmed),
        )

    def calibration_check(self) -> dict:
        """Sanity-check numbers used to assert the axis span is a whole number
        of grid squares and that horizontal/vertical scale agree."""
        n_sq = (self.Rx - self.Lx) / self.pitch
        return dict(
            page=self.page, lattice_pitch_px=self.pitch,
            axis_span_px=round(self.Rx - self.Lx, 1),
            squares=round(n_sq, 3), squares_err=round(abs(n_sq - round(n_sq)), 4),
            px_per_ft=round(self.ppf, 4), ft_per_square=round(self.span_ft / n_sq, 3),
            datum_const=round(self.datum, 3), ocr_inliers=f"{self.ocr_inliers}/{self.ocr_total}",
        )
