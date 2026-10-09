# INFRA — GDOT Earthwork Plan Reader

Reads GDOT road cross-section drawings (PDF), traces the **existing ground**
(dashed) and **proposed design** (solid) surfaces, measures fill / cut area per
cross-section and computes **earthwork volume per road** (average-end-area).

```
backend/    FastAPI + the gdot_earthwork image-processing pipeline (Python)
frontend/   React + Vite UI
data/       (git-ignored) put your input PDFs here -- they are never committed
```

## Two processing modes

| Mode (UI toggle) | Endpoint | Input | Output |
|---|---|---|---|
| **Full plan set** | `POST /api/process_plan_set` | Whole vector plan set PDF (real text layer). Cross-section pages are auto-detected from `NNN+NN` station labels; other pages are skipped. | Stations grouped into roads, fill/cut ft² per station, volume segments + totals (cy) per road, coloured overlay per station, CSV export. |
| **Scanned sheets** | `POST /api/process` | Scanned 19/23-series PDF (one cross-section per page) + page list, e.g. `1,2,3,20-25`. | Per page: fill/cut/net ft², per-grid-cell ledger, calibration + OCR datum checks, warnings, coloured overlay. |

Other endpoints: `GET /api/health` (checks `pdfimages`, `pdftoppm`, `tesseract`), `GET /api/presets`.

## Setup

System packages (required by the pipeline):

```bash
# Debian/Ubuntu
sudo apt-get install poppler-utils tesseract-ocr
# macOS
brew install poppler tesseract
# Windows: install Poppler + Tesseract and add both to PATH
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --port 8811 --reload
```

Plan-set overlay PNGs are also saved under `backend/local_results/<timestamp>/`
(override with the `RESULTS_DIR` env var). That folder is git-ignored.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The UI calls `http://127.0.0.1:8811` by default; set `VITE_API_BASE` in
`frontend/.env.local` to point somewhere else.

## Command line / diagnostic tools (backend/)

```bash
# scanned-sheet pipeline, no server
python -m gdot_earthwork.cli --pdf ../data/19series.pdf --pages 1,2,3,20-25 --out outputs

# plan-set pipeline on a page range, prints stations / roads / volumes
python scripts/test_real_plan_set.py ../data/highway_planning1.pdf --start 94 --end 102

# draw detected cross-section boundaries on one page
python scripts/test_real_splitter.py ../data/highway_planning1.pdf --page 96

# text layer vs. scan? stacked vs. side-by-side sections?
python scripts/diagnose_cross_sections.py ../data/plan.pdf --page 5
python scripts/check_pdf_content_type.py ../data/plan.pdf --page 96
```

## Pipeline (backend/gdot_earthwork)

| Module | Stage |
|---|---|
| `config.py` | All tunables (`PipelineConfig`) + named presets (`19series`). |
| `pipeline/io_extract.py` | Pull page images out of scanned PDFs (`pdfimages`, fallback `pdftoppm`). |
| `pipeline/grid_geometry.py` | Detect grid lattice + plot axes, strip grid without breaking curves. |
| `pipeline/ocr_datum.py` | OCR the elevation gutter (tesseract) and fit the datum by consensus. |
| `pipeline/preprocess.py` | Remove text glyphs; split dashed (ground) vs solid (design) ink. |
| `pipeline/curve_trace.py` | DP path tracing, gap refinement, despiking, buried-service trimming. |
| `pipeline/section.py` | `Section`: runs the above for one cross-section image. |
| `pipeline/area.py` | Grid-cell fill/cut area ledger. |
| `pipeline/visualize.py` | Green (fill) / red (cut) overlay with grid cells. |
| `pipeline/pipeline_run.py` | Scanned-sheet orchestration (`process_pdf`). |
| `pipeline/section_splitter.py` | Vector PDFs: find cross-section regions from text, vector gridlines, sheet metadata. |
| `pipeline/raster_section_splitter.py` | Scanned PDFs: find stacked regions + OCR station labels. *Not wired into any endpoint yet; unvalidated.* |
| `pipeline/road_grouping.py` | Group stations into roads by document order; flag repeated corridors. |
| `pipeline/volume.py` | Average-end-area volume per road (cy). |
| `pipeline/plan_set_run.py` | Plan-set orchestration (`process_plan_set`). |

## Accuracy against hand-labeled takeoffs

`backend/scripts/evaluate_labels.py` scores the plan-set pipeline against the
hand-coloured takeoffs (see *Labeled data* below) and the results are shown on
the **Accuracy** page of the UI.

For each project it runs the app's own plan-set code on the clean vector PDF,
extracts the green (fill) / red (cut) colouring from the scanned takeoff,
aligns the two pages automatically, and compares every cross-section:
fill/cut area (ft², using the true scale read from the sheet's axis numbers),
overlap (IoU), average-end-area volume per road, and whether the app read the
sheet's scale correctly.

```bash
cd backend
python scripts/evaluate_labels.py --data ../data/EARTHWORK
```

It writes `frontend/src/data/accuracy.json` and a few example comparison
images to `frontend/public/accuracy/`; rebuild/reload the frontend to see them.

## Input data

Input PDFs are **not** in the repo (many are 25–127 MB, above GitHub's limits).
Keep them in `data/` (git-ignored) or upload them through the UI. Every `*.pdf`,
`*.zip` and `*.png` is ignored by git.

### Labeled data

The original data drop contains **hand-labeled cut/fill takeoffs**: scanned
sheets where an estimator coloured **fill green** and **cut red**, paired with
the same sheets unlabeled. These can serve as ground truth to validate the
pipeline's overlays. File names are not consistent: sometimes the *EARTHWORK* file is the
labeled one, sometimes it is the clean vector original.

| Project | Labeled (coloured) file | Labeled pages | Unlabeled counterpart(s) |
|---|---|---|---|
| Perry Creek | `PERRY CREEK RD- TAKEOFF EARTHWORK.pdf` | 12/12 | `PERRY CREEK- EARTHWORK.pdf` (vector) |
| SR 136 Lookout Creek | `… - EARTHWORK MAINLINE.pdf` | 11/17 | `…- MAINLINE.pdf` |
| SR 136 Lookout Creek | `… - EARTHWORK -STAGE 1.pdf` | 11/15 | `… - STAGE 1.pdf` |
| SR 136 Lookout Creek | `…- EARTHWORK -STAGE 2.pdf` | 5/15 | `… - STAGE 2.pdf` |
| SR 332 | `SR 332  - MAINLINE.pdf` | 21/27 | `SR-332 EARTHWORK.pdf` (vector) |
| SR 70 | `SR 70 - CROSS SECTION.pdf` | 19/29 | `SR 70- EARTHWORK.pdf` (vector) |
| Webb Creek | `WEEB CREEK - EARTHWORK.pdf` | 4/5 | `WEBB CREEK- EARTHWORK.pdf` (vector) |
| Mountain Ind Blvd | `… - MAINLINE EARTHWORK.pdf` | 18/43 | `… - MAINLINE.pdf` (= `23_series_sample.pdf`, identical file) |
| Mountain Ind Blvd | `… -EARTHWORK -STAGE 1.pdf` | 9/12 | `… - STAGE 2.pdf` (12 pages) |
| River Side Road | `… - EARTHWORK MAINLINE.pdf` | 14/27 | `… - MAINLINE.pdf` |
| River Side Road | `… - EARTHWORK -STAGE  2.pdf` | 9/26 | `… - STAGE 2.pdf` |
| Lakeside Drive | `LAKESIDE DRIVE - EARTHWORK-MAINLINE.pdf` | 2/3 | `LAKESIDE.pdf` |
| Florence, Hamilton, Mtn Ind Blvd Stage 2, River Side Stage 3 | small / thin markings only | ~0 detected | – |

"Labeled pages" counts pages with a visible amount of red/green markup (automatic
colour detection, so pages with very thin markings may be missed). No labels exist
as structured data (CSV/JSON): the labels are only colours on the drawings. The
plan sets `19series.pdf` and `highway_planning1.pdf` are unlabeled.
