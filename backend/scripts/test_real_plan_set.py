"""
Runs process_plan_set() against a page range of your REAL plan set PDF,
using the gdot_earthwork package already copied into webapp_backend.

Usage (from backend/):

    python scripts/test_real_plan_set.py path/to/highway_planning1.pdf --start 94 --end 102

Prints every station found, every road group, every volume segment, and
saves each region's coloured fill/cut overlay PNG so you can open a few
and visually confirm the green/red overlay actually tracks the real
ground/design lines on the sheet -- numbers alone can't catch a
miscalibrated overlay that happens to still produce plausible-looking
area totals.
"""
import argparse
import os
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gdot_earthwork.config import get_config  # noqa: E402
from gdot_earthwork.pipeline.plan_set_run import process_plan_set  # noqa: E402


def extract_page_range(pdf_path, start, end, out_path):
    doc = fitz.open(pdf_path)
    sub = fitz.open()
    sub.insert_pdf(doc, from_page=start - 1, to_page=end - 1)
    sub.save(out_path)
    sub.close()
    doc.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=1)
    ap.add_argument("--out-dir", default="plan_set_test_out")
    ap.add_argument("--preset", default="19series")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    sub_path = os.path.join(args.out_dir, "temp_page_range.pdf")
    extract_page_range(args.pdf, args.start, args.end, sub_path)

    cfg = get_config(args.preset)
    result = process_plan_set(sub_path, cfg, work_dir=os.path.join(args.out_dir, "work"),
                              out_dir=args.out_dir)

    print(f"pages_scanned: {result.pages_scanned}")
    print(f"cross_section_pages: {result.cross_section_pages}")
    if result.skipped_regions:
        print("skipped_regions:")
        for s in result.skipped_regions:
            print(" ", s)

    print()
    print(f"stations found: {len(result.stations)}")
    for s in result.stations:
        print(f"  {s.station_label:>8}  fill={s.fill_ft2:8.2f} ft2  cut={s.cut_ft2:8.2f} ft2  "
              f"image={s.coloured_image_path}")

    print()
    print(f"roads: {len(result.roads)}")
    for road, vol in zip(result.roads, result.volumes):
        print(f"  {road.label}: {[e.station_label for e in road.entries]}")
        for flag in road.flags:
            print(f"    FLAG: {flag}")
        for seg in vol.segments:
            warn = f"  ({seg.warning})" if seg.warning else ""
            print(f"    {seg.station_from} -> {seg.station_to}: "
                  f"fill={seg.fill_cy:.1f}cy cut={seg.cut_cy:.1f}cy net={seg.net_cy:+.1f}cy{warn}")
        print(f"    TOTAL: fill={vol.total_fill_cy:.1f}cy cut={vol.total_cut_cy:.1f}cy "
              f"net={vol.total_net_cy:+.1f}cy")

    print()
    print(f"Coloured overlay images saved under: {args.out_dir}/")
    print("Open a few and visually confirm the green/red overlay actually")
    print("tracks the real ground/design lines on the sheet -- plausible")
    print("numbers alone don't rule out a miscalibrated crop.")


if __name__ == "__main__":
    main()