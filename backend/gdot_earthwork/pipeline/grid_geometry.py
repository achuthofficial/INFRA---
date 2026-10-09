"""
Stage 2 -- find the drawing's grid lattice, plot axes, and strip the
lattice out of the ink mask without breaking the curves crossing it.
"""
from __future__ import annotations

import numpy as np


def runs1d(a: np.ndarray, tol: int = 3) -> list[tuple[int, int]]:
    """Group a sorted index array into (start, end) runs, merging gaps <= tol."""
    if len(a) == 0:
        return []
    out, s, p = [], a[0], a[0]
    for v in a[1:]:
        if v - p > tol:
            out.append((int(s), int(p)))
            s = v
        p = v
    out.append((int(s), int(p)))
    return out


def dilate1d(v: np.ndarray, k: int) -> np.ndarray:
    """Binary dilation of a 1-D boolean vector by k samples each way."""
    out = v.copy()
    for s in range(1, k + 1):
        out[:-s] |= v[s:]
        out[s:] |= v[:-s]
    return out


def detect_lattice(ink: np.ndarray, frac: float = 0.45):
    """Grid lines are the only strokes that run (almost) the full height / width.
    Returns run-groups of columns and rows that qualify."""
    H, W = ink.shape
    return (
        runs1d(np.where(ink.sum(0) > frac * H)[0]),
        runs1d(np.where(ink.sum(1) > frac * W)[0]),
    )


def strip_grid(ink: np.ndarray, V, H_, bridge: int = 5) -> np.ndarray:
    """Delete the lattice, then SURGICALLY repair the curves it was crossing.

    Naively zeroing a grid column also punches a hole through every data curve
    that crossed it, shattering each curve into fragments. So for each
    deleted band we re-connect only those rows where ink exists on BOTH sides
    within +-`bridge` px -- i.e. we restore continuity without restoring the grid.
    """
    m = ink.copy()
    for s, e in V:
        m[:, max(0, s - 1):e + 2] = 0
    for s, e in H_:
        m[max(0, s - 1):e + 2, :] = 0
    for s, e in V:
        a, b = s - 2, e + 2
        if a < 0 or b >= m.shape[1]:
            continue
        both = dilate1d(m[:, a].astype(bool), bridge) & dilate1d(m[:, b].astype(bool), bridge)
        m[:, a + 1:b] |= both[:, None].astype(np.uint8)
    for s, e in H_:
        a, b = s - 2, e + 2
        if a < 0 or b >= m.shape[0]:
            continue
        both = dilate1d(m[a, :].astype(bool), bridge) & dilate1d(m[b, :].astype(bool), bridge)
        m[a + 1:b, :] |= both[None, :].astype(np.uint8)
    return m


def plot_axes(ink: np.ndarray, V, r0: int, r1: int, pitch: float) -> tuple[float, float]:
    """The two verticals bounding the plot are the ones carrying elevation tick
    stubs along the WHOLE height. Scoring by ink volume alone gets fooled by a
    steep embankment; scoring by *vertical coverage* does not."""
    nb = max(4, int((r1 - r0) / (pitch / 5)))
    edges = np.linspace(r0, r1, nb + 1).astype(int)
    cov = lambda b: sum(1 for a, z in zip(edges[:-1], edges[1:]) if b[a:z].any()) / nb
    sc = []
    for s, e in V:
        if e - s + 1 > 4:
            continue
        sc.append((
            (s + e) / 2.0,
            cov(ink[:, max(0, s - 13):max(0, s - 2)].max(1)),
            cov(ink[:, e + 3:e + 14].max(1)),
        ))
    mid = np.median([c for c, _, _ in sc])
    return (
        max([x for x in sc if x[0] < mid], key=lambda t: t[2])[0],
        max([x for x in sc if x[0] > mid], key=lambda t: t[1])[0],
    )
