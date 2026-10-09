"""
Stage 3 (continued) -- trace the ground and design surfaces through a
noisy, dashed, gapped ink mask, then clean the traced chain up.

Pipeline within this module, applied to both ground and design:
    candidates()      per-column ink midpoints
    best_path()        max-scoring DP chain through those candidates
    snap_top()          (design only) recentre on the topmost stroke
    refine_gaps()       recall pass: look for missed dashes inside big gaps
    despike()/densify()  outlier rejection + dense per-column array
    trim_buried_tail()  drop false "cut" caused by buried services
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

from .grid_geometry import runs1d


def candidates(mask: np.ndarray, max_run: int = 30) -> list[list[float]]:
    """Per column, the mid-point of every vertical ink run = a curve observation."""
    out = []
    for x in range(mask.shape[1]):
        col = np.where(mask[:, x])[0]
        c = []
        for s, e in runs1d(col, tol=2):
            if e - s + 1 <= max_run:
                c.append((s + e) / 2.0)
            else:
                c += [float(s), float(e)]
        out.append(c)
    return out


def best_path(cands, reward=3.0, win=260, slope=0.6, slack=8.0, gap_pen=0.04) -> dict[int, float]:
    """Max-scoring chain through the candidate points (Viterbi over a DAG).

    A greedy left-to-right tracker breaks at the first long dash gap and then
    coasts away from the curve. Scoring globally -- +reward per point used,
    -|dy| for roughness, -gap_pen per skipped column -- recovers the whole
    surface including the stretch hidden behind the proposed template.

    Vectorized over the sliding window: the original was a pure-Python
    `for i: for j in range(start, i)` double loop, which is fine for a
    handful of candidate points but scales very badly on a wide, ink-dense
    real drawing with thousands of them -- confirmed as the dominant cost
    of the whole per-region pipeline on real GDOT plan sets (~5s/region,
    the large majority of total processing time). This computes the same
    scores with numpy array ops over each window instead of a Python-level
    inner loop. Tie-breaking matches exactly: np.argmax returns the FIRST
    occurrence of the max value for a tie, same as the original's strict
    `s > score[i]` comparison while iterating j in increasing order."""
    pts = [(x, y) for x, c in enumerate(cands) for y in c]
    if not pts:
        return {}
    n = len(pts)
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    score = np.full(n, reward)
    prev = np.full(n, -1)
    start = 0
    for i in range(n):
        xi, yi = xs[i], ys[i]
        while xs[start] < xi - win:
            start += 1
        if start >= i:
            continue
        wx = xs[start:i]
        wy = ys[start:i]
        dx = xi - wx
        dy = np.abs(yi - wy)
        valid = (dx > 0) & (dy <= slope * dx + slack)
        if not valid.any():
            continue
        s = score[start:i] + reward - dy - gap_pen * (dx - 1)
        s = np.where(valid, s, -np.inf)
        j_local = int(np.argmax(s))
        if s[j_local] > score[i]:
            score[i] = s[j_local]
            prev[i] = start + j_local
    k = int(np.argmax(score))
    path = []
    while k >= 0:
        path.append(k)
        k = prev[k]
    return {int(xs[i]): float(ys[i]) for i in reversed(path)}


def snap_top(mask: np.ndarray, chain: dict[int, float], rad: int = 9) -> dict[int, float]:
    """The template is drawn as a thin box (surface + pavement structure), so the
    finished surface is the TOPMOST stroke -- and we want that stroke's CENTRE.
    Taking its upper edge biases the whole surface up by half a stroke width,
    which shows up directly as a fill/cut error."""
    out = {}
    for x, y in chain.items():
        lo, hi = max(0, int(y) - rad), min(mask.shape[0], int(y) + rad + 1)
        w = np.where(mask[lo:hi, x])[0]
        if len(w) == 0:
            out[x] = y
            continue
        a, b = runs1d(w, tol=1)[0]
        out[x] = float(lo + (a + b) / 2.0)
    return out


def despike(y: np.ndarray, win: int, thresh_px: float) -> tuple[np.ndarray, int]:
    """Reject outliers only -- do NOT smooth. Leader lines, witness ticks and
    dimension arrows that survived the glyph filter show up as isolated jumps;
    genuine break-points (ditch invert, catch point, shoulder hinge) must come
    through untouched, so flagged samples are replaced by interpolation from
    their good neighbours rather than by a filtered value."""
    ok = ~np.isnan(y)
    idx = np.where(ok)[0]
    if len(idx) < win:
        return y, 0
    v = y[idx].copy()
    bad = np.abs(v - median_filter(v, size=win, mode="nearest")) > thresh_px
    if bad.any() and (~bad).sum() >= 2:
        v[bad] = np.interp(idx[bad], idx[~bad], v[~bad])
    out = y.copy()
    out[idx] = v
    return out, int(bad.sum())


def trim_buried_tail(x: np.ndarray, gpx: np.ndarray, dpx: np.ndarray, ppf: float,
                      run_ft: float, depth_ft: float):
    """Temporary pipes and other buried services run on past the template's toe.
    They read as a LONG, DEEP run of 'proposed below existing' that reaches the
    end of the chain -- a graded cut always closes back onto the ground inside
    the template, so it never looks like this."""
    ov = ~np.isnan(gpx) & ~np.isnan(dpx)
    if ov.sum() < 10:
        return dpx, []
    c = np.where(ov)[0]
    xx = x[c]
    d = (gpx[c] - dpx[c]) / ppf
    sign = np.sign(np.where(np.abs(d) < 0.10, 0, d))
    runs, i = [], 0
    while i < len(d):
        if sign[i] < 0:
            j = i
            while j < len(d) and sign[j] <= 0:
                j += 1
            runs.append((i, j - 1, xx[j - 1] - xx[i], float(-d[i:j].min())))
            i = j
        else:
            i += 1
    out = dpx.copy()
    killed = []
    for a, b, L, dep in runs:
        if L < run_ft or dep < depth_ft:
            continue
        if xx[-1] - xx[b] <= 2.0:
            out[c[a]:] = np.nan
            killed.append(dict(side="right", x_from=round(float(xx[a]), 2),
                                x_to=round(float(xx[-1]), 2),
                                run_ft=round(float(L), 1), depth_ft=round(dep, 2)))
        elif xx[a] - xx[0] <= 2.0:
            out[:c[b] + 1] = np.nan
            killed.append(dict(side="left", x_from=round(float(xx[0]), 2),
                                x_to=round(float(xx[b]), 2),
                                run_ft=round(float(L), 1), depth_ft=round(dep, 2)))
    return out, killed


def refine_gaps(chain: dict[int, float], full_mask: np.ndarray, ppf: float,
                 min_gap_ft: float, tol_px: float):
    """Inside a long interpolation gap the surface's own dashes usually still
    exist -- they were simply absorbed into a solid component they touch, so the
    dash/solid split never offered them. Re-hunt for ink near the interpolated
    path in the FULL mask and accept it when it is close enough to be the same
    surface. This is a recall pass, not a smoother: it only ever adds points."""
    if len(chain) < 2:
        return chain, 0
    xs = np.array(sorted(chain))
    ys = np.array([chain[x] for x in xs])
    add = {}
    for i in np.where(np.diff(xs) / ppf > min_gap_ft)[0]:
        a, b, ya, yb = xs[i], xs[i + 1], ys[i], ys[i + 1]
        for x in range(a + 1, b):
            yp = ya + (yb - ya) * (x - a) / (b - a)
            col = np.where(full_mask[:, x])[0]
            if not len(col):
                continue
            best = min(((s_ + e) / 2 for s_, e in runs1d(col, tol=2)), key=lambda c: abs(c - yp))
            if abs(best - yp) <= tol_px:
                add[x] = best
    out = dict(chain)
    out.update(add)
    return out, len(add)


def interp_spans(chain: dict[int, float], W: int, ppf: float, warn_ft: float):
    """Boolean per column: True where the surface is only a straight-line guess
    across a gap wider than `warn_ft`. Area computed there is not supported by
    ink and is reported separately rather than quietly folded into the total."""
    m = np.zeros(W, bool)
    if len(chain) < 2:
        return m, 0.0
    xs = np.array(sorted(chain))
    d = np.diff(xs) / ppf
    for i in np.where(d > warn_ft)[0]:
        m[xs[i]:xs[i + 1] + 1] = True
    return m, float(d.max()) if len(d) else 0.0


def densify(chain: dict[int, float], W: int) -> np.ndarray:
    """Chain -> dense per-column array, linearly interpolated, NaN outside."""
    g = np.full(W, np.nan)
    if not chain:
        return g
    xs = np.array(sorted(chain))
    ys = np.array([chain[x] for x in xs])
    grid = np.arange(W)
    m = (grid >= xs[0]) & (grid <= xs[-1])
    g[m] = np.interp(grid[m], xs, ys)
    return g
