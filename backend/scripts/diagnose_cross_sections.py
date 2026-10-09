"""
Run this against your ACTUAL plan-set PDF to answer the two questions that
decide whether CrossSectionSplitter (text-extraction based) will work:

    1. Does this PDF have a real text layer, or is it scanned/raster?
    2. When a page has multiple cross-sections, are they stacked
       vertically or arranged side by side?

Usage:
    pip install pymupdf pillow
    python diagnose_cross_sections.py your_plan_set.pdf --page 5

Run it on a few different pages -- a plan set can mix a text-layer cover
sheet with scanned cross-section sheets, so one page's answer doesn't
necessarily hold for the whole document.
"""
import argparse
import re
import sys

import fitz  # PyMuPDF
from PIL import Image, ImageDraw


def get_spans(page):
    spans = []
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line["spans"]:
                txt = span["text"].strip()
                if txt:
                    ox, oy = span["origin"]
                    spans.append((round(oy, 1), round(ox, 1), txt, round(span["size"], 1)))
    return spans


def classify_candidates(spans):
    station_re = re.compile(r"^(\d+)\+(\d{2})$")
    offset_re = re.compile(r"^-?\d{1,3}$")
    stations, offsets = [], []
    for y, x, txt, sz in spans:
        if station_re.match(txt):
            stations.append((y, x, txt))
        elif offset_re.match(txt) and -150 <= int(txt) <= 150:
            offsets.append((y, x, txt))
    return stations, offsets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=1, help="1-indexed page to inspect")
    ap.add_argument("--save-image", default="diagnostic_page.png",
                     help="annotated page image to save for visual inspection")
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    if args.page < 1 or args.page > len(doc):
        print(f"PDF has {len(doc)} pages; --page must be 1..{len(doc)}")
        sys.exit(1)
    page = doc[args.page - 1]
    pw, ph = page.rect.width, page.rect.height

    spans = get_spans(page)
    print(f"--- page {args.page} of {len(doc)} ---")
    print(f"page size: {pw:.0f} x {ph:.0f} pt")
    print(f"total text spans found: {len(spans)}")

    if len(spans) == 0:
        print()
        print("RESULT: no text layer on this page.")
        print("This page is very likely scanned/raster -- text-based splitting")
        print("(CrossSectionSplitter) will NOT work here. You'd need an")
        print("OCR-based or image/grid-detection approach instead, like the")
        print("raster pipeline (detect_lattice / Section) built earlier.")
        doc.close()
        return

    print("sample spans (y, x, text, font size) -- first 10:")
    for s in spans[:10]:
        print(" ", s)

    stations, offsets = classify_candidates(spans)
    print()
    print(f"station-label candidates (NNN+NN pattern): {len(stations)}")
    for s in stations[:20]:
        print(" ", s)
    print(f"offset-label candidates (-150..150 integers): {len(offsets)}")

    if len(stations) == 0:
        print()
        print("RESULT: text layer exists, but nothing matched the station")
        print("pattern. Either stations aren't formatted as NNN+NN on this")
        print("sheet, or they sit somewhere the splitter isn't looking --")
        print("check the sample spans above for the actual station text.")

    if stations:
        xs = [x for _, x, _ in stations]
        ys = [y for y, _, _ in stations]
        x_spread = max(xs) - min(xs)
        y_spread = max(ys) - min(ys)
        print()
        print(f"station label X spread: {x_spread:.0f} pt (page width {pw:.0f} pt)")
        print(f"station label Y spread: {y_spread:.0f} pt (page height {ph:.0f} pt)")
        if x_spread > 0.25 * pw and y_spread < 0.4 * ph:
            print("RESULT: labels spread across X, clustered in Y --> sections")
            print("are most likely SIDE BY SIDE. CrossSectionSplitter's current")
            print("_find_axis_rows (Y-only clustering) will NOT separate these")
            print("correctly -- it needs an X-partitioning step added first.")
        elif y_spread > 0.25 * ph and x_spread < 0.4 * pw:
            print("RESULT: labels spread across Y, clustered in X --> sections")
            print("are most likely STACKED VERTICALLY. The current Y-band")
            print("approach should work as-is.")
        else:
            print("RESULT: spread is significant in both X and Y -- ambiguous")
            print("from numbers alone. Check the saved annotated image below.")

    zoom = 2
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    draw = ImageDraw.Draw(img)
    for y, x, _ in stations:
        px, py = x * zoom, y * zoom
        draw.ellipse([px - 5, py - 5, px + 5, py + 5], outline=(220, 30, 30), width=2)
    for y, x, _ in offsets:
        px, py = x * zoom, y * zoom
        draw.ellipse([px - 3, py - 3, px + 3, py + 3], outline=(30, 60, 220), width=1)
    img.save(args.save_image)

    print()
    print(f"Annotated page image saved to: {args.save_image}")
    print("Red circles = station-label candidates. Blue circles = offset-label")
    print("candidates. Open the image and look at how the dots cluster to")
    print("visually confirm side-by-side vs. stacked, and to sanity-check the")
    print("regex matches against what's actually printed on the sheet.")

    doc.close()


if __name__ == "__main__":
    main()