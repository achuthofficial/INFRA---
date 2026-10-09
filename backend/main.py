"""
gdot_earthwork API -- thin HTTP layer over the pipeline package.

Endpoints:
    GET  /api/health            liveness + system dependency check
    GET  /api/presets           available drawing-series presets
    POST /api/process           scanned cross-section PDF + page list -> per-page
                                ledgers, totals, warnings, coloured overlay PNG
    POST /api/process_plan_set  whole (vector) plan set PDF -> cross-sections
                                auto-detected, grouped by road, volume per road.
                                Overlay PNGs are also kept under RESULTS_DIR.

Nothing here does image processing itself -- it validates the request,
calls gdot_earthwork.pipeline_run, and serializes the result. Keep it
that way: new pipeline logic goes in the package, not in route handlers.
"""
from __future__ import annotations

import base64
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gdot_earthwork.config import PRESETS, get_config
from gdot_earthwork.pipeline.io_extract import check_system_deps
from gdot_earthwork.pipeline.pipeline_run import process_pdf
from gdot_earthwork.pipeline.plan_set_run import process_plan_set

# Plan-set overlay PNGs are persisted here, one timestamped folder per run.
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", Path(__file__).parent / "local_results"))

app = FastAPI(title="GDOT Earthwork Pipeline API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to the real frontend origin before deploying
    allow_methods=["*"],
    allow_headers=["*"],
)


class PageResultOut(BaseModel):
    page: int
    fill_ft2: float
    cut_ft2: float
    net_ft2: float
    cells: int
    warnings: list[str]
    diagnostics: dict
    calibration: dict
    coloured_image_b64: str  # data:image/png;base64,... payload
    ledger: list[dict]


class ProcessResponse(BaseModel):
    pages: list[PageResultOut]
    preset: str


def _parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    if not pages:
        raise ValueError("no pages specified")
    return sorted(set(pages))


def _encode_png(path: str) -> str:
    img = cv2.imread(path)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError(f"failed to encode {path}")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


@app.get("/api/health")
def health():
    deps = check_system_deps()
    return {"ok": all(deps.values()), "dependencies": deps}


@app.get("/api/presets")
def presets():
    return {"presets": list(PRESETS.keys())}


@app.post("/api/process", response_model=ProcessResponse)
async def process(
    file: UploadFile = File(...),
    pages: str = Form(...),
    preset: str = Form("19series"),
):
    if file.content_type not in ("application/pdf", "application/x-pdf") and \
       not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")

    try:
        page_list = _parse_pages(pages)
    except ValueError as e:
        raise HTTPException(400, f"Could not parse pages {pages!r}: {e}")

    try:
        cfg = get_config(preset)
    except KeyError as e:
        raise HTTPException(400, str(e))

    deps = check_system_deps()
    if not all(deps.values()):
        missing = [k for k, ok in deps.items() if not ok]
        raise HTTPException(500, f"Server is missing required binaries: {missing}")

    job_dir = Path(tempfile.mkdtemp(prefix=f"gdot_{uuid.uuid4().hex[:8]}_"))
    pdf_path = job_dir / Path(file.filename).name
    try:
        with pdf_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            results = process_pdf(
                str(pdf_path), page_list, cfg=cfg,
                work_dir=str(job_dir / "work"), out_dir=str(job_dir / "outputs"),
            )
        except ValueError as e:
            # bad page number / sheet layout mismatch -- a client-fixable error
            raise HTTPException(422, str(e))
        except RuntimeError as e:
            raise HTTPException(500, str(e))

        out_pages = []
        for p, r in results.items():
            out_pages.append(PageResultOut(
                page=p,
                fill_ft2=round(float(r.totals["fill_ft2"]), 3),
                cut_ft2=round(float(r.totals["cut_ft2"]), 3),
                net_ft2=round(float(r.totals["net_ft2"]), 3),
                cells=int(r.totals["cells"]),
                warnings=r.warnings,
                diagnostics=r.diagnostics,
                calibration=r.calibration,
                coloured_image_b64=_encode_png(r.coloured_image_path),
                ledger=r.ledger.to_dict(orient="records"),
            ))
        out_pages.sort(key=lambda x: x.page)
        return ProcessResponse(pages=out_pages, preset=preset)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


@app.post("/api/process_plan_set")
async def process_plan_set_endpoint(
    file: UploadFile = File(...),
    preset: str = Form("19series"),
):
    """Upload a whole plan set PDF -- no page list. Every page is scanned;
    a page counts as a cross-section page exactly when CrossSectionSplitter
    finds at least one region on it. Stations are grouped into roads and
    trapezoidal volume is computed per road."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")
    try:
        cfg = get_config(preset)
    except KeyError as e:
        raise HTTPException(400, str(e))

    deps = check_system_deps()
    if not all(deps.values()):
        missing = [k for k, ok in deps.items() if not ok]
        raise HTTPException(500, f"Server is missing required binaries: {missing}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = Path(tempfile.mkdtemp(prefix=f"gdot_plan_{uuid.uuid4().hex[:8]}_"))
    persist_dir = RESULTS_DIR / timestamp
    persist_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / Path(file.filename).name

    try:
        with pdf_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)

        result = process_plan_set(
            str(pdf_path), cfg,
            work_dir=str(job_dir / "work"), out_dir=str(persist_dir),
        )

        roads_out = []
        for road, vol in zip(result.roads, result.volumes):
            roads_out.append({
                "road_label": road.label,
                "road_name": road.road_name,
                "series_id": road.series_id,
                "duplicate_of": road.duplicate_of,
                "station_range": road.station_range,
                "flags": road.flags,
                "stations": [
                    {
                        "station_label": e.station_label,
                        "station_ft": e.station_ft,
                        "page_number": e.page_number,
                        "fill_ft2": round(e.ref.fill_ft2, 2),
                        "cut_ft2": round(e.ref.cut_ft2, 2),
                        "coloured_image_b64": _encode_png(e.ref.coloured_image_path)
                                              if e.ref.coloured_image_path else None,
                    }
                    for e in road.entries
                ],
                "volume_segments": [
                    {
                        "from": s.station_from, "to": s.station_to,
                        "length_ft": s.length_ft, "fill_cy": s.fill_cy,
                        "cut_cy": s.cut_cy, "net_cy": s.net_cy, "warning": s.warning,
                    }
                    for s in vol.segments
                ],
                "total_fill_cy": round(vol.total_fill_cy, 1),
                "total_cut_cy": round(vol.total_cut_cy, 1),
                "total_net_cy": round(vol.total_net_cy, 1),
            })

        return {
            "pages_scanned": result.pages_scanned,
            "cross_section_pages": result.cross_section_pages,
            "skipped_regions": result.skipped_regions,
            "timing": result.timing,
            "roads": roads_out,
        }
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
