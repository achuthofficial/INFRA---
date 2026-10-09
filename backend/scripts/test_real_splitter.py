"""
Runs CrossSectionSplitter against one real page and shows exactly what it
produced: how many regions, what station each was paired with, and where
it thinks each region's top/bottom boundary is -- drawn directly on the
page image so you can check the bands line up with the real boxes.

Usage (from backend/):
    python scripts/test_real_splitter.py path/to/plan_set.pdf --page 96
"""
import argparse
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gdot_earthwork.pipeline.section_splitter import CrossSectionSplitter  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--save-image", default="split_result.png")
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    page = doc[args.page - 1]

    splitter = CrossSectionSplitter()
    regions = splitter.split(page, page_number=args.page)

    print(f"--- page {args.page}: {len(regions)} region(s) detected ---")
    for r in regions:
        print(f"  station {r.station_label:>8}  y_top={r.y_top:7.1f}  y_bottom={r.y_bottom:7.1f}  "
              f"height={r.y_bottom - r.y_top:6.1f}pt  elev_range={r.elevation_range}  "
              f"n_elev={len(r.elevations):2d}  n_offsets={len(r.offsets):2d}")

    if not regions:
        print("No regions detected -- split() returned empty. Check that this")
        print("page actually has the expected NNN+NN station labels and >=10")
        print("offset labels per axis row (see the earlier diagnostic script).")

    zoom = 2
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    draw = ImageDraw.Draw(img)
    colors = [(220, 30, 30), (30, 140, 30), (30, 90, 220), (200, 130, 20)]
    for i, r in enumerate(regions):
        c = colors[i % len(colors)]
        draw.line([(0, r.y_top * zoom), (pix.width, r.y_top * zoom)], fill=c, width=2)
        draw.line([(0, r.y_bottom * zoom), (pix.width, r.y_bottom * zoom)], fill=c, width=3)
        draw.text((10, r.y_top * zoom + 4), f"{r.station_label}  elev {r.elevation_range}", fill=c)
    img.save(args.save_image)
    print(f"\nBoundary visualization saved to: {args.save_image}")
    print("Thin line = top of region, thick line = bottom of region (the")
    print("detected axis row). Check these actually bracket each real")
    print("cross-section box and don't clip into the neighboring one.")

    doc.close()


if __name__ == "__main__":
    main()
