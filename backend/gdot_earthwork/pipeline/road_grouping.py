"""
Group a sequence of cross-section stations into separate roads.

Two roads can share the exact same step interval (e.g. a mainline
stationed 100+00, 100+50, 101+00... and a side road stationed 20+00,
20+50, 21+00...) so grouping can NOT be done by sorting all stations by
raw station value and looking for gaps -- that would interleave the two
roads' values into nonsense groups. It also can't be done by station
magnitude alone (nothing guarantees a side road's numbers stay lower
than the mainline's).

The one reliable signal available is DOCUMENT ORDER: a real plan set lays
out one road's cross-section sheets consecutively, in increasing station
order, before moving on to the next road. So this walks entries in the
order they were found (page order, then top-to-bottom within a page) and
starts a new group whenever the sequence stops looking like "the same
road, stepping forward by a consistent interval."

NOT YET VALIDATED against a real road-to-road transition in an actual
plan set -- only against synthetic data shaped like the scenario
described. Before trusting this, run it across a page range in a real
plan set you know contains two different roads, and confirm the group
boundary lands where the roads actually change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass
class StationEntry:
    """One cross-section's station, in document order."""
    station_label: str
    station_ft: float
    page_number: int
    ref: object = None  # attach the source CrossSectionRegion (or anything) here
    road_name: str = "unknown"
    series_id: str = "unknown"


_STAGE_RE = re.compile(r"STAGE\s*(\d+)", re.IGNORECASE)


@dataclass
class RoadGroup:
    label: str
    entries: list[StationEntry] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # ambiguous-transition notes
    road_name: str = "unknown"
    series_id: str = "unknown"
    station_list: list = field(default_factory=list)
    duplicate_of: str | None = None  # label of an earlier group this one repeats

    @property
    def station_range(self):
        if not self.entries:
            return (None, None)
        return (self.entries[0].station_ft, self.entries[-1].station_ft)

    def finalize_metadata(self):
        if self.entries:
            self.road_name = self.entries[0].road_name
            self.series_id = self.entries[0].series_id
        self.station_list = [e.station_label for e in self.entries]

    @staticmethod
    def display_label(road_name: str, series_id: str, sheet_title_text: str) -> str:
        stage_m = _STAGE_RE.search(sheet_title_text)
        if stage_m:
            condition = f"Stage {stage_m.group(1)} Staging"
        elif "STAGING" in sheet_title_text.upper():
            condition = "Staging"
        else:
            condition = "Final Design"
        return f"{road_name} — {condition}" if road_name != "unknown" else f"{series_id} — {condition}"


def _established_interval(group: RoadGroup) -> float | None:
    diffs = sorted(
        b.station_ft - a.station_ft
        for a, b in zip(group.entries, group.entries[1:])
        if b.station_ft - a.station_ft > 0
    )
    if not diffs:
        return None
    return diffs[len(diffs) // 2]  # median -- robust to one bad outlier


def _station_ft_set(group: RoadGroup) -> set[float]:
    return {e.station_ft for e in group.entries}


def annotate_possible_duplicate_corridors(groups: list[RoadGroup]) -> None:
    """Flag (not merge) groups whose station range closely overlaps an
    earlier group's -- e.g. the same physical road's cross-sections
    printed twice in one plan set for two different sheet series
    (confirmed on a real GDOT set: a title sheet showed ONE continuous
    project alignment, station 11+65 to 49+25, while this grouper had
    split its cross-sections into two "roads" covering that same range
    twice, ~35 pages apart, because station-number restart was the only
    signal available).

    The sheet series (.dgn file name from the title block, see
    section_splitter.extract_sheet_metadata) is used to tell the cases apart:
      - same series, >=95% overlap: a repeat of the same sections --
        marked via `duplicate_of`.
      - different series: same road, different design condition (e.g.
        mainline vs. a staging set) -- computed independently, flagged.
      - series unknown: ambiguous -- flagged for a manual check.

    Nothing is merged or discarded: which overlapping series should count
    toward earthwork totals isn't recoverable from station numbers alone."""
    seen: list[RoadGroup] = []
    for group in groups:
        group.finalize_metadata()
        this_set = _station_ft_set(group)
        for other in seen:
            other_set = _station_ft_set(other)
            if not this_set or not other_set:
                continue
            overlap = len(this_set & other_set) / min(len(this_set), len(other_set))
            if overlap < 0.7:
                continue
            known = "unknown" not in (group.series_id, other.series_id)
            if known and group.series_id == other.series_id and overlap >= 0.95:
                group.duplicate_of = other.label
                group.flags.append(
                    f"{overlap:.0%} station overlap with {other.label} on the same sheet "
                    f"series ({group.series_id}) -- very likely a repeat of the same "
                    f"cross-sections; check before adding both to earthwork totals."
                )
            elif known and group.series_id != other.series_id:
                group.flags.append(
                    f"{overlap:.0%} station overlap with {other.label}, but different "
                    f"sheet series ({group.series_id} vs {other.series_id}) -- "
                    f"same road, different design condition. NOT a duplicate; computed independently."
                )
            else:
                group.flags.append(
                    f"{overlap:.0%} of this road's stations exactly match {other.label}'s "
                    f"station range -- this is very likely the SAME physical road shown "
                    f"again in a separate sheet series, not a second road. Check sheet "
                    f"titles/drawing numbers on both page ranges before treating these as "
                    f"separate corridors for earthwork totals."
                )
            break
        seen.append(group)


def group_into_roads(
    entries: list[StationEntry],
    min_interval_ft: float = 10.0,
    max_gap_multiplier: float = 4.0,
) -> list[RoadGroup]:
    """Split `entries` (must already be in DOCUMENT order -- do not
    pre-sort by station_ft) into RoadGroups.

    A new group starts when:
      - the station goes DOWN or repeats relative to the previous entry
        (a road's stationing only increases as you move along it; a drop
        means the sequence moved to a different road's sheets), or
      - the step to the next station is more than `max_gap_multiplier`
        times the group's own established interval -- a jump far bigger
        than that road's normal spacing, well beyond what a couple of
        missed/undetected sections would produce.

    A step that's merely LARGER than usual (a plausible missed section)
    stays in the same group but adds a flag to it, rather than being
    silently absorbed or silently treated as a new road.

    IMPORTANT CAVEAT, confirmed on real data: a station-number restart is
    NOT proof of a different physical road -- the same road's cross-
    sections can legitimately appear twice in one plan set, in two
    separate sheet series (e.g. grading vs. a separate environmental/
    permit set), and that looks identical to a genuine second road from
    station numbers alone. See annotate_possible_duplicate_corridors(),
    called below, which flags (but does not resolve) that ambiguity.
    """
    if not entries:
        return []

    groups: list[RoadGroup] = []
    current = RoadGroup(label=f"road_{len(groups) + 1}")
    current.entries.append(entries[0])

    for prev, entry in zip(entries, entries[1:]):
        diff = entry.station_ft - prev.station_ft

        if diff <= 0:
            groups.append(current)
            current = RoadGroup(label=f"road_{len(groups) + 1}")
            current.entries.append(entry)
            continue

        interval = _established_interval(current)
        if interval is None:
            current.entries.append(entry)  # not enough history yet to judge
            continue

        if diff > max_gap_multiplier * max(interval, min_interval_ft):
            groups.append(current)
            current = RoadGroup(label=f"road_{len(groups) + 1}")
            current.entries.append(entry)
        else:
            if diff > 1.5 * interval:
                current.flags.append(
                    f"gap of {diff:.0f} ft between {prev.station_label} and "
                    f"{entry.station_label} is larger than this road's usual "
                    f"{interval:.0f} ft step -- possible missed/undetected "
                    f"section (kept in this road, worth a manual check)."
                )
            current.entries.append(entry)

    groups.append(current)
    annotate_possible_duplicate_corridors(groups)
    return groups
