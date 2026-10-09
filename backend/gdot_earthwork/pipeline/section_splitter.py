"""
Locates cross-section regions on a page of a vector (real text layer) PDF
plan set, using station labels (NNN+NN) and axis tick labels read directly
from the PDF text -- no OCR, no raster grid detection.

Validated against a real GDOT plan set (S.R. 156 at Salacoa Creek): correct
region count and boundaries on both a 3-section page and a 2-section page,
including a page whose elevation range differed from its neighbors (proof
the axis values are read per-page, not a stuck placeholder). NOT yet
validated on a page with 4 sections, or on sections arranged side by side
rather than stacked vertically -- see CrossSectionSplitter's docstring.
"""
import re


class CrossSectionRegion:
    """One cross-section graph on a page."""

    def __init__(self, station_label, station_ft, y_top, y_bottom, page_number,
                 drawing_number="", elevations=None, offsets=None):
        self.station_label = station_label
        self.station_ft = station_ft
        self.y_top = y_top
        self.y_bottom = y_bottom
        self.page_number = page_number
        self.drawing_number = drawing_number
        self.elevations = elevations or []
        self.offsets = offsets or []

    @property
    def elevation_range(self):
        if not self.elevations:
            return (0.0, 0.0)
        return (min(self.elevations), max(self.elevations))

    @property
    def offset_range(self):
        if not self.offsets:
            return (-140.0, 140.0)
        return (min(self.offsets), max(self.offsets))


_DGN_RE = re.compile(r"[\w\-.]+\.dgn", re.IGNORECASE)
_ROAD_RE = re.compile(r"\bS\.?\s?R\.?\s*-?\s*\d+\b", re.IGNORECASE)


def extract_sheet_metadata(spans) -> dict:
    """Pulls road name + sheet-series identity from the title block text
    already available on every page (no extra PDF pass needed)."""
    all_text = " ".join(txt for _, _, txt, _ in spans)
    dgn = _DGN_RE.search(all_text)
    road = _ROAD_RE.search(all_text)
    return {
        "road_name": road.group(0).strip() if road else "unknown",
        "series_id": dgn.group(0).strip() if dgn else "unknown",
    }


def extract_vector_gridlines(page, y_top: float, y_bottom: float, min_len_frac: float = 0.85):
    """Real grid-line positions read straight from the PDF's vector paths,
    for this region's Y-band -- no raster threshold, no ambiguity."""
    pw = page.rect.width
    h_rows, v_cols = {}, {}
    for d in page.get_drawings():
        width = d.get("width") or 0.0
        for item in d["items"]:
            if item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            if abs(p0.y - p1.y) < 0.05 and y_top - 2 <= p0.y <= y_bottom + 2:
                length = abs(p1.x - p0.x)
                if length >= min_len_frac * pw:
                    y = round(p0.y, 1)
                    h_rows[y] = max(h_rows.get(y, 0), width)
            elif abs(p0.x - p1.x) < 0.05:
                length = abs(p1.y - p0.y)
                if length >= min_len_frac * (y_bottom - y_top):
                    x = round(p0.x, 1)
                    v_cols[x] = max(v_cols.get(x, 0), width)
    return h_rows, v_cols   # {position_in_pt: line_width_in_pt}


class CrossSectionSplitter:
    """Assumes cross-sections are stacked vertically on the page (validated);
    a page with sections arranged side by side would need _find_axis_rows
    extended to partition by X before clustering by Y -- not yet needed for
    the plan set this was validated against."""

    def __init__(self, right_margin_fraction=0.85, axis_label_tolerance=2.0):
        self.right_margin_x = right_margin_fraction
        self.axis_tol = axis_label_tolerance

    def split(self, page, page_number, drawing_number=""):
        """Split page into cross-section regions. Returns list of CrossSectionRegion.
        Returns [] for any page that isn't a cross-section sheet -- this IS the
        auto-detection: a page counts as a cross-section page exactly when this
        returns a non-empty list."""
        rect = page.rect
        pw = rect.width

        spans = self._get_spans(page)

        right_x = pw * self.right_margin_x
        station_labels = []
        for y, x, txt, sz in spans:
            if x > right_x and sz > 8.0:
                m = re.match(r"^(\d+)\+(\d{2})$", txt.strip())
                if m:
                    sta_ft = int(m.group(1)) * 100 + int(m.group(2))
                    station_labels.append((y, txt.strip(), sta_ft))

        if not station_labels:
            return []
        station_labels.sort(key=lambda s: s[0])

        axis_rows = self._find_axis_rows(spans, pw)
        if not axis_rows:
            return []

        left_x = pw * 0.12
        elev_spans = []
        for y, x, txt, sz in spans:
            if x < left_x:
                m = re.match(r"^(\d{3,4})$", txt.strip())
                if m:
                    val = float(m.group(1))
                    if 100 < val < 9999:
                        elev_spans.append((y, val))

        regions = []
        for i, axis_y in enumerate(axis_rows):
            if i == 0:
                y_top = max(axis_y - (axis_rows[1] - axis_rows[0]) if len(axis_rows) > 1 else axis_y - 180, 30.0)
            else:
                y_top = axis_rows[i - 1]
            y_bottom = axis_y

            best_sta, best_dist = None, float("inf")
            for sy, label, ft in station_labels:
                if y_top <= sy <= y_bottom:
                    dist = abs(sy - (y_top + y_bottom) / 2)
                    if dist < best_dist:
                        best_dist = dist
                        best_sta = (label, ft)
            if not best_sta:
                continue

            region_elevs = sorted(set(
                val for ey, val in elev_spans if y_top - 5 <= ey <= y_bottom + 5
            ))
            region_offsets = self._get_offsets_at_row(spans, axis_y)

            regions.append(CrossSectionRegion(
                station_label=best_sta[0], station_ft=best_sta[1],
                y_top=y_top, y_bottom=y_bottom, page_number=page_number,
                drawing_number=drawing_number, elevations=region_elevs,
                offsets=region_offsets,
            ))

        regions.sort(key=lambda r: r.station_ft)
        return regions

    def _get_spans(self, page):
        text_dict = page.get_text("dict")
        spans = []
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if txt:
                        ox, oy = span["origin"]
                        spans.append((round(oy, 1), round(ox, 1), txt, round(span["size"], 1)))
        return spans

    def _find_axis_rows(self, spans, page_width):
        offset_spans = []
        for y, x, txt, sz in spans:
            m = re.match(r"^-?\d{1,3}$", txt)
            if m:
                val = int(txt)
                if -150 <= val <= 150 and 0.1 * page_width < x < 0.95 * page_width:
                    offset_spans.append((y, val))
        if not offset_spans:
            return []
        offset_spans.sort()
        rows = {}
        for y, val in offset_spans:
            placed = False
            for row_y in rows:
                if abs(y - row_y) < self.axis_tol:
                    rows[row_y].append(val)
                    placed = True
                    break
            if not placed:
                rows[y] = [val]
        return sorted(y for y, vals in rows.items() if len(vals) >= 10)

    def _get_offsets_at_row(self, spans, axis_y):
        offsets = []
        for y, x, txt, sz in spans:
            if abs(y - axis_y) < self.axis_tol:
                m = re.match(r"^-?\d{1,3}$", txt)
                if m:
                    val = int(txt)
                    if abs(val) <= 200:
                        offsets.append(val)
        return sorted(set(offsets))
