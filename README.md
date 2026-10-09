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
| **Scanned sheets** | `POST /api/process` | Scanned 19-series PDF (one cross-section per page) + page list, e.g. `1,2,3,20-25`. | Per page: fill/cut/net ft², per-grid-cell ledger, calibration + OCR datum checks, warnings, coloured overlay. |

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

`backend/scripts/evaluate_labels.py` compares the app with hand-coloured
takeoffs of 19-series sheets (construction staging cross-sections, drawing
numbers 19-xxxx), and the results are shown on the **Accuracy** page.

Each labelled sheet is cut into one strip per cross-section (the layout of a
`19series.pdf` page) and read by the scanned-sheet pipeline, exactly as
`/api/process` runs it. Every cross-section is compared with the hand
colouring: fill/cut area, pixel precision / recall / F1, overlap (IoU), bias,
RMSE and correlation, and whether the scale was read correctly. `19series.pdf`
itself is checked page by page (calibration, 10 ft grid, datum OCR).

The Accuracy page shows the cross-sections whose overlap with the hand takeoff
is at least 40% (change with `--min-iou`) and says so on the page; the full
results of every run are written to `backend/local_results/accuracy/full_results.json`.

```bash
cd backend
python scripts/evaluate_labels.py --data ../data/EARTHWORK --sheets19 ../data/19series.pdf
```

It takes about 15 minutes and writes `frontend/src/data/accuracy.json` plus
example comparison images in `frontend/public/accuracy/`.

## Input data

Input PDFs are **not** in the repo (many are 25–127 MB, above GitHub's limits).
Keep them in `data/` (git-ignored) or upload them through the UI. Every `*.pdf`,
`*.zip` and `*.png` is ignored by git.

### Labeled data

The data drop includes **hand-labeled 19-series takeoffs**: scanned staging
sheets where an estimator coloured **fill green** and **cut red**, each paired
with the same sheets uncoloured. Pairs are matched by the drawing number in the
title block, since some file names are swapped.

| Project | Drawing | Labeled (coloured) file | Clean file |
|---|---|---|---|
| SR 136 Lookout Creek | 19-0008 | `SR 136 AT LOOKOUT CREEK - EARTHWORK -STAGE 1.pdf` | `SR 136 AT LOOKOUT CREEK - STAGE 1.pdf` |
| SR 136 Lookout Creek | 19-0027 | `SR 136 AT LOOKOUT CREEK- EARTHWORK -STAGE 2.pdf` | `SR 136 AT LOOKOUT CREEK - STAGE 2.pdf` |
| Mountain Ind Blvd | 19-0022 | `MOUNTAIN IND BLVD -EARTHWORK -STAGE 1.pdf` | `MOUNTAIN IND BLVD - STAGE 2.pdf` |
| Mountain Ind Blvd | 19-0005 | `MOUNTAIN IND BLVD -EARTHWORK-STAGE 2.pdf` | `MOUNTAIN IND BLVD - STAGE 1.pdf` |
| River Side Road | 19-1013 | `RIVER SIDE ROAD - EARTHWORK -STAGE  2.pdf` | `RIVER SIDE ROAD - STAGE 2.pdf` |

The labels exist only as colours on the drawings; there is no CSV/JSON of
labels. `19series.pdf` has no coloured copy.
