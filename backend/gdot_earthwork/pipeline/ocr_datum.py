"""
Stage 2 (continued) -- recover the absolute elevation datum by OCR'ing the
elevation-label gutter and taking a consensus vote across noisy readings.

If tesseract is unavailable, or no reading survives the consensus check,
callers fall back to a *relative* datum (see Section.datum_source) --
areas and cut/fill are still computed correctly, elevations are just not
tied to AMSL.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np


def _gutter_ocr(m, x0, y0, y1, psm, scale, ndig=3):
    crop = 255 - m[y0:y1, x0:x0 + 134] * 255
    if (crop < 128).sum() < 20:
        return []
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    f = tempfile.mktemp(suffix=".png")
    cv2.imwrite(f, crop)
    o = subprocess.run(
        ["tesseract", f, "stdout", "tsv", "--psm", psm,
         "-c", "tessedit_char_whitelist=0123456789"],
        capture_output=True, text=True,
    )
    os.unlink(f)
    out = []
    for ln in o.stdout.splitlines()[1:]:
        fl = ln.split("\t")
        t = (fl[11] or "").strip() if len(fl) >= 12 else ""
        if re.fullmatch(r"\d{%d}" % ndig, t) and int(t) % 10 == 0:
            out.append((y0 + (int(fl[7]) + int(fl[9]) / 2 - 40) / scale, int(t)))
    return out


def read_elev_labels(ink, V, H_, right_axis, lat_rows, gutter_width: int = 134):
    """Read the RIGHT-hand elevation gutter (the left gutter's leading digit is
    overprinted by the sheet frame). Two readers are pooled, because neither is
    reliable alone on a 1990s scan: one pass over the whole strip, and one tight
    crop per grid line. Wrong readings are thrown out by consensus, not trusted."""
    if not shutil.which("tesseract"):
        return []
    m = ink.copy()
    for s_, e in V:
        m[:, max(0, s_ - 1):e + 2] = 0
    for s_, e in H_:
        m[max(0, s_ - 1):e + 2, :] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    x0 = int(right_axis) + 6
    pool = []
    for sc in (6, 8):
        pool += _gutter_ocr(m, x0, 0, m.shape[0], "6", sc)
    for r in lat_rows:
        a, b = int(r - 26), int(r + 26)
        if a < 0 or b > m.shape[0]:
            continue
        for psm in ("7", "8", "13"):
            for sc in (6, 8):
                pool += _gutter_ocr(m, x0, a, b, psm, sc)
    return pool


def fit_datum(pool, lat_rows, pitch, grid_ft: float = 10.0):
    """Every label votes for one constant C = elev + row / px_per_ft. Snap each
    label to the grid line it annotates first -- OCR returns the row of the text,
    which sits ~15 px above that line and is worth real bias if believed.
    Then keep the largest agreeing block and average it (RANSAC in one dimension)."""
    if not pool:
        return None, 0, 0
    ppf = pitch / grid_ft
    lat = np.asarray(lat_rows)
    votes = []
    for r, e in pool:
        j = int(np.argmin(abs(lat - r)))
        if abs(lat[j] - r) < pitch * 0.35:
            votes.append(e + lat[j] / ppf)
    if not votes:
        return None, 0, len(pool)
    best = max(votes, key=lambda c: sum(1 for k in votes if abs(k - c) < 0.5))
    inl = [c for c in votes if abs(c - best) < 0.5]
    if len(inl) < 2:
        return None, len(inl), len(votes)
    return float(np.mean(inl)), len(inl), len(votes)
