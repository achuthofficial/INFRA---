"""
Checks whether a page's content is vector paths (crisp at any render zoom)
or an embedded raster image (can blur/fatten under resampling, the way
the synthetic test's PNG-embedded-in-PDF fixture did).

Usage:
    python check_pdf_content_type.py highway_planning1.pdf --page 96
"""
import argparse
import fitz

ap = argparse.ArgumentParser()
ap.add_argument("pdf")
ap.add_argument("--page", type=int, default=1)
args = ap.parse_args()

doc = fitz.open(args.pdf)
page = doc[args.page - 1]

images = page.get_images()
drawings = page.get_drawings()

print(f"--- page {args.page} ---")
print(f"embedded raster images on this page: {len(images)}")
print(f"vector drawing paths on this page:    {len(drawings)}")

if len(drawings) > 50 and len(images) == 0:
    print()
    print("RESULT: pure vector content. Cropped renders at any zoom should")
    print("stay crisp -- the resampling issue seen in the synthetic test is")
    print("unlikely to apply here.")
elif len(images) > 0:
    print()
    print("RESULT: this page has embedded raster image(s). If the ground/")
    print("design curves are part of one of those images (rather than drawn")
    print("as separate vector strokes on top), cropping and re-rendering at")
    print("a different zoom COULD reproduce the resampling issue seen in the")
    print("synthetic test. Worth visually inspecting a cropped region's PNG")
    print("output directly once the pipeline runs on this page.")
else:
    print()
    print("RESULT: ambiguous -- little of either. Inspect the page directly.")

doc.close()