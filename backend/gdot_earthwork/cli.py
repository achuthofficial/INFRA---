"""
Command-line entrypoint. Equivalent to running the original notebook
top-to-bottom, but with the PDF path, page list, and preset as arguments
instead of hardcoded globals.

Usage:
    python -m gdot_earthwork.cli --pdf 19series.pdf --pages 1,2,3,20,70 \
        --preset 19series --out outputs --work work
"""
from __future__ import annotations

import argparse
import sys

from .pipeline.pipeline_run import process_pdf, totals_table


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GDOT cross-section grid-cell area pipeline")
    ap.add_argument("--pdf", required=True, help="Path to the cross-section PDF")
    ap.add_argument("--pages", required=True, help="Comma/range list, e.g. 1,2,3,20-25")
    ap.add_argument("--preset", default="19series", help="Named config preset (see config.py)")
    ap.add_argument("--work", default="work", help="Scratch dir for extracted page images")
    ap.add_argument("--out", default="outputs", help="Output dir for ledgers + coloured PNGs")
    args = ap.parse_args(argv)

    pages = parse_pages(args.pages)
    results = process_pdf(args.pdf, pages, cfg=args.preset, work_dir=args.work, out_dir=args.out)

    print(totals_table(results).to_string())
    for r in results.values():
        for w in r.warnings:
            print(f"WARNING: {w}")
    totals_table(results).to_csv(f"{args.out}/totals_approach1.csv")
    print(f"\nledgers and coloured images written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
