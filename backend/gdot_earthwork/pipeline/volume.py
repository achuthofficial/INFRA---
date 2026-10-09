"""
Average-end-area (trapezoidal) earthwork volume between consecutive
same-road cross-sections.

This module does NOT compute cross-sectional area itself -- it assumes
each station already carries a computed fill_ft2 / cut_ft2. That's the
piece still missing from the vector-PDF track: tracing the ground/design
curves inside each cross-section box (located by CrossSectionSplitter)
and measuring the fill/cut area between them, the same role area.py /
curve_trace.py play for the raster pipeline. Whatever eventually supplies
that number -- reusing the raster grid-cell method on a cropped
sub-image, or a new vector-based curve extraction -- only needs to expose
.station_ft, .station_label, .fill_ft2, .cut_ft2 to plug in here.

IMPORTANT: call average_end_area_volume() once per RoadGroup, never
across roads -- the formula assumes consecutive stations are physically
adjacent along the same corridor. Pass a mixed list and it will happily
compute a meaningless volume between two unrelated roads without
complaint.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol


class HasStationArea(Protocol):
    station_label: str
    station_ft: float
    fill_ft2: float
    cut_ft2: float


@dataclass
class VolumeSegment:
    station_from: str
    station_to: str
    length_ft: float
    fill_cy: float
    cut_cy: float
    net_cy: float  # positive = net fill
    warning: str | None = None


@dataclass
class RoadVolumeResult:
    road_label: str
    segments: list[VolumeSegment] = field(default_factory=list)

    @property
    def total_fill_cy(self) -> float:
        return sum(s.fill_cy for s in self.segments)

    @property
    def total_cut_cy(self) -> float:
        return sum(s.cut_cy for s in self.segments)

    @property
    def total_net_cy(self) -> float:
        return self.total_fill_cy - self.total_cut_cy


def average_end_area_volume(
    stations: list[HasStationArea],
    road_label: str = "road",
    gap_warn_multiplier: float = 2.0,
) -> RoadVolumeResult:
    """Trapezoidal / average-end-area volume between each consecutive pair
    of `stations` (all from ONE road -- see module docstring).

        V = (A1 + A2) / 2 * L        [ft^3, converted here to cubic yards]

    This is exact for a uniform prismoid and the standard approximation
    used for AASHTO/GDOT earthwork estimates otherwise. Accuracy degrades
    as the interval between stations grows or the two end areas differ a
    lot -- `gap_warn_multiplier` flags that rather than silently
    accepting it.
    """
    if len(stations) < 2:
        return RoadVolumeResult(road_label=road_label, segments=[])

    ordered = sorted(stations, key=lambda s: s.station_ft)
    diffs = [b.station_ft - a.station_ft for a, b in zip(ordered, ordered[1:])]
    # Use the MOST COMMON observed interval as the "normal" baseline -- not
    # the minimum. Real station lists aren't perfectly uniform: engineers
    # routinely insert an extra station at a point of interest (start of a
    # structure, a PI point, a culvert) between two otherwise-regular
    # stations, producing one or two short gaps alongside the road's normal
    # spacing everywhere else. Using the minimum as "typical" means that one
    # inserted station becomes the baseline, and every genuinely normal
    # segment gets flagged as "too large" -- confirmed on real data, where a
    # single inserted station turned a warning meant for rare anomalies into
    # one that fired on 24 of 25 segments. The mode reflects what the road
    # actually does most of the time and isn't thrown off by a handful of
    # intentional insertions.
    typical = Counter(round(d) for d in diffs).most_common(1)[0][0] if diffs else 0.0

    segments = []
    for a, b, L in zip(ordered, ordered[1:], diffs):
        fill_ft3 = (a.fill_ft2 + b.fill_ft2) / 2.0 * L
        cut_ft3 = (a.cut_ft2 + b.cut_ft2) / 2.0 * L
        fill_cy = fill_ft3 / 27.0
        cut_cy = cut_ft3 / 27.0
        warning = None
        if typical and L > gap_warn_multiplier * typical:
            warning = (
                f"interval {L:.0f} ft is more than {gap_warn_multiplier:g}x this "
                f"road's typical {typical:.0f} ft step -- volume over this span "
                f"is a coarser approximation than the rest of the road."
            )
        segments.append(VolumeSegment(
            station_from=a.station_label, station_to=b.station_label,
            length_ft=L, fill_cy=round(fill_cy, 2), cut_cy=round(cut_cy, 2),
            net_cy=round(fill_cy - cut_cy, 2), warning=warning,
        ))

    return RoadVolumeResult(road_label=road_label, segments=segments)
