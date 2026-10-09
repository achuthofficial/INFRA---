"""
Stage 1 -- pull the raw page image out of a scanned cross-section PDF.

The PDF is a scan: every page is one embedded JPEG at its native size.
`pdfimages` pulls that JPEG out losslessly -- no resampling, no
interpolation -- which matters because every measurement downstream is
made in pixels. `pdftoppm` (rasterize-from-scratch at 150dpi) is the
fallback for pages where no embedded image is found.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from typing import Iterable


def extract_pages(
    pdf: str,
    pages: Iterable[int],
    work_dir: str,
) -> dict[int, str]:
    """Extract `pages` (1-indexed) from `pdf` into `work_dir` as PNGs.

    Returns {page_number: path_to_png}. Cached: a page already extracted
    into work_dir is not re-extracted.
    """
    os.makedirs(work_dir, exist_ok=True)
    out: dict[int, str] = {}
    for p in pages:
        dst = os.path.join(work_dir, f"page_{p:03d}.png")
        if not os.path.exists(dst):
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(
                    ["pdfimages", "-f", str(p), "-l", str(p), "-png", pdf,
                     os.path.join(td, "im")],
                    capture_output=True, text=True,
                )
                got = sorted(glob.glob(os.path.join(td, "im*.png")))
                if not got:
                    r2 = subprocess.run(
                        ["pdftoppm", "-f", str(p), "-l", str(p), "-r", "150",
                         "-png", pdf, os.path.join(td, "im")],
                        capture_output=True, text=True,
                    )
                    got = sorted(glob.glob(os.path.join(td, "im*.png")))
                    if not got and r2.returncode != 0:
                        raise ValueError(
                            f"Could not extract page {p} from {os.path.basename(pdf)!r} -- "
                            f"the PDF may not have that many pages, or the file is not a "
                            f"valid PDF. ({r2.stderr.strip().splitlines()[-1] if r2.stderr.strip() else 'no detail'})"
                        )
                if not got:
                    raise ValueError(
                        f"Could not extract page {p} from {os.path.basename(pdf)!r} -- "
                        f"the PDF may not have that many pages."
                    )
                shutil.copy(got[0], dst)
        out[p] = dst
    return out


def check_system_deps() -> dict[str, bool]:
    """Report availability of the external binaries this pipeline shells out to."""
    return {
        "pdfimages": shutil.which("pdfimages") is not None,
        "pdftoppm": shutil.which("pdftoppm") is not None,
        "tesseract": shutil.which("tesseract") is not None,
    }
