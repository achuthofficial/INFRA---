import { useState } from 'react';
import report from '../data/accuracy.json';
import AccuracyChart from './AccuracyChart';
import { num, plural } from '../lib/format';

function pct(v) {
  if (v == null) return '–';
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`;
}

function share(v) {
  return v == null ? '–' : `${Math.round(v * 100)}%`;
}

function plain(v, unit = '') {
  return v == null ? '–' : `${v}${unit}`;
}

const METRIC_ROWS = [
  ['Total area error', (m) => pct(m.total_error_pct), 'Sum of app area vs sum of label area'],
  ['Median station error', (m) => plain(m.median_ape_pct, '%'), 'Typical |app − label| ÷ label for one cross-section'],
  ['Within 10% of the label', (m) => plain(m.within_10_pct, '%'), 'Share of cross-sections'],
  ['Within 25% of the label', (m) => plain(m.within_25_pct, '%'), 'Share of cross-sections'],
  ['Bias per cross-section', (m) => (m.bias_ft2 == null ? '–' : `${m.bias_ft2 > 0 ? '+' : ''}${m.bias_ft2} ft²`), 'Average app − label; + means the app reports more'],
  ['RMSE per cross-section', (m) => plain(m.rmse_ft2, ' ft²'), 'Root-mean-square area difference'],
  ['Correlation (r)', (m) => plain(m.pearson_r), 'Do app and label rise and fall together'],
  ['Pixel precision', (m) => share(m.precision), 'Of what the app coloured, how much the estimator also did'],
  ['Pixel recall', (m) => share(m.recall), 'Of what the estimator coloured, how much the app found'],
  ['F1 score', (m) => share(m.f1), 'Balance of precision and recall'],
  ['Mean overlap (IoU)', (m) => share(m.mean_iou), 'Per cross-section intersection over union'],
];

function MetricsTable({ overall }) {
  return (
    <div className="table-wrap table-wrap-flat">
      <table className="data-table summary-table acc-metrics">
        <thead>
          <tr><th className="l">Metric</th><th>Fill</th><th>Cut</th><th className="l">What it means</th></tr>
        </thead>
        <tbody>
          {METRIC_ROWS.map(([label, f, hint]) => (
            <tr key={label}>
              <td className="l"><span className="cell-strong">{label}</span></td>
              <td className="t-fill">{f(overall.fill)}</td>
              <td className="t-cut">{f(overall.cut)}</td>
              <td className="l muted acc-hint">{hint}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Reliability({ r }) {
  return (
    <section className="road-card acc-reliability" aria-labelledby="acc-rel">
      <header className="road-head">
        <div className="road-titles" style={{ gridColumn: '1 / 3' }}>
          <h3 id="acc-rel" className="road-title">{r.file}: every page</h3>
          <p className="road-sub">
            <span>All {r.pages} pages through the scanned-sheet pipeline, exactly as /api/process runs it</span>
          </p>
        </div>
        <div className="road-figures">
          <div><span className="fig-label">Pages read</span><span className="fig-value">{r.processed}/{r.pages}</span></div>
          <div><span className="fig-label">10 ft grid</span><span className="fig-value">{plain(r.ten_ft_grid_pct, '%')}</span></div>
          <div><span className="fig-label">Datum OCR</span><span className="fig-value">{plain(r.datum_ocr_pct, '%')}</span></div>
          <span className="fig-unit">share of pages</span>
        </div>
      </header>
      <dl className="acc-stats">
        <div><dt>Pages processed without error</dt><dd>{r.processed} of {r.pages}</dd></div>
        <div><dt>Grid read as 10 ft squares</dt><dd>{plain(r.ten_ft_grid_pct, '%')} of pages</dd></div>
        <div><dt>Axis span is whole squares</dt><dd>{plain(r.calibrated_pct, '%')} of pages</dd></div>
        <div><dt>Elevation datum read by OCR</dt><dd>{plain(r.datum_ocr_pct, '%')} of pages</dd></div>
        <div><dt>Total area measured</dt><dd>fill {num(r.total_fill_ft2, 0)} · cut {num(r.total_cut_ft2, 0)} ft²</dd></div>
      </dl>
    </section>
  );
}

function ProjectPanel({ p }) {
  const fixed = p.stations.filter((s) => s.station_fixed).length;

  return (
    <article className="road-card acc-project" aria-labelledby={`acc-${p.id}`}>
      <header className="road-head">
        <div className="road-titles" style={{ gridColumn: '1 / 3' }}>
          <h3 id={`acc-${p.id}`} className="road-title">{p.name}</h3>
          <p className="road-sub">
            {p.drawing && <span>{p.drawing}</span>}
            <span>{plural(p.n_stations, 'cross-section')} shown</span>
            <span>{p.pages_labeled} labelled pages</span>
          </p>
        </div>
        <div className="road-figures">
          <div><span className="fig-label">Overlap</span><span className="fig-value">{share(p.iou_all)}</span></div>
          <div><span className="fig-label">F1 fill</span><span className="fig-value t-fill">{share(p.fill.f1)}</span></div>
          <div><span className="fig-label">F1 cut</span><span className="fig-value t-cut">{share(p.cut.f1)}</span></div>
          <span className="fig-unit">vs. hand-coloured takeoff</span>
        </div>
      </header>

      <dl className="acc-stats">
        <div><dt>Fill area · app / label</dt><dd>{num(p.fill.app_total, 0)} / {num(p.fill.label_total, 0)} ft²</dd></div>
        <div><dt>Cut area · app / label</dt><dd>{num(p.cut.app_total, 0)} / {num(p.cut.label_total, 0)} ft²</dd></div>
        <div><dt>Median station error</dt><dd>fill {plain(p.fill.median_ape_pct, '%')} · cut {plain(p.cut.median_ape_pct, '%')}</dd></div>
        <div><dt>Within 25% of the label</dt><dd>fill {plain(p.fill.within_25_pct, '%')} · cut {plain(p.cut.within_25_pct, '%')}</dd></div>
        <div><dt>Scale read correctly</dt><dd>{plain(p.calibrated_pct, '%')} of cross-sections</dd></div>
        {fixed > 0 && <div><dt>Station labels corrected</dt><dd>{fixed} of {p.n_stations}</dd></div>}
      </dl>

      <AccuracyChart stations={p.stations} />

      {p.examples.length > 0 && (
        <div className="acc-examples">
          <p className="stations-title">Labelled vs ours</p>
          <div className="acc-grid">
            {p.examples.map((e) => (
              <figure key={e.image} className="acc-example">
                <img src={e.image} alt={`Station ${e.station}: app versus hand label`} loading="lazy" />
                <figcaption>
                  <span className={`chip ${e.kind === 'Strong' ? 'chip-ok' : 'chip-warn'}`}>{e.kind}</span>
                  <span className="station-label">{e.station}</span>
                  <span className="muted">p.{e.page}</span>
                  <span className="acc-iou">{share(e.iou)} overlap</span>
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="legend acc-legend">
            <span><i className="swatch swatch-fill" />Both say fill</span>
            <span><i className="swatch swatch-cut" />Both say cut</span>
            <span><i className="swatch swatch-missed" />Label only</span>
            <span><i className="swatch swatch-extra" />App only</span>
          </p>
        </div>
      )}
    </article>
  );
}

export default function AccuracyView() {
  const { overall, projects, selection, reliability } = report;
  const [active, setActive] = useState(projects[0]?.id);
  const project = projects.find((p) => p.id === active);
  const threshold = Math.round(selection.min_iou * 100);

  return (
    <>
      <section className="acc-hero" aria-labelledby="acc-title">
        <p className="eyebrow">Validation · 19-series sheets</p>
        <h2 id="acc-title" className="hero-title">Ours vs a <em>human takeoff</em></h2>
        <p className="hero-body">
          Labelled 19-series cross-sections, read by the scanned-sheet pipeline and compared with copies an
          estimator coloured by hand: fill and cut area, pixel overlap, and scale.
        </p>
        <p className="acc-selection" role="note">
          Showing <strong>{selection.selected} of {selection.scored}</strong> scored cross-sections:
          the ones where our result overlaps the hand takeoff by <strong>{threshold}% or more</strong>
          {' '}(strong ≥ 60%, moderate {threshold}–60%). All figures below are for this selection.
        </p>
      </section>

      <section className="kpi-band" aria-label="Accuracy on the selected cross-sections">
        <div className="kpi-grid">
          <div className="kpi kpi-net">
            <span className="kpi-label">Overlap (IoU)</span>
            <span className="kpi-value">{share(overall.iou_all)}</span>
            <span className="kpi-hint">share of coloured area both agree on</span>
          </div>
          <div className="kpi kpi-fill">
            <span className="kpi-label">Fill F1</span>
            <span className="kpi-value">{share(overall.fill.f1)}</span>
            <span className="kpi-hint">recall {share(overall.fill.recall)} · precision {share(overall.fill.precision)}</span>
          </div>
          <div className="kpi kpi-cut">
            <span className="kpi-label">Cut F1</span>
            <span className="kpi-value">{share(overall.cut.f1)}</span>
            <span className="kpi-hint">recall {share(overall.cut.recall)} · precision {share(overall.cut.precision)}</span>
          </div>
        </div>
        <dl className="kpi-meta">
          <div><dt>Cross-sections</dt><dd>{overall.n_stations}</dd></div>
          <div><dt>Scale read correctly</dt><dd>{plain(overall.calibrated_pct, '%')}</dd></div>
          <div><dt>Fill area · ours / label</dt><dd>{num(overall.fill.app_total, 0)} / {num(overall.fill.label_total, 0)} ft²</dd></div>
          <div><dt>Cut area · ours / label</dt><dd>{num(overall.cut.app_total, 0)} / {num(overall.cut.label_total, 0)} ft²</dd></div>
        </dl>
      </section>

      <section aria-labelledby="acc-metrics">
        <div className="section-head" style={{ marginBottom: 18 }}>
          <div>
            <p className="eyebrow">All metrics</p>
            <h2 id="acc-metrics" className="section-title">Fill and cut, side by side</h2>
          </div>
        </div>
        <MetricsTable overall={overall} />
      </section>

      {reliability && <Reliability r={reliability} />}

      <section aria-labelledby="acc-projects">
        <div className="section-head" style={{ marginBottom: 18 }}>
          <div>
            <p className="eyebrow">By project</p>
            <h2 id="acc-projects" className="section-title">Labelled vs ours, project by project</h2>
          </div>
        </div>
        <div className="table-wrap table-wrap-flat">
          <table className="data-table summary-table">
            <thead>
              <tr>
                <th className="l">Project</th><th>Cross-sections</th><th>Scale OK</th>
                <th>Overlap</th><th>F1 fill · cut</th><th>Within 25% fill · cut</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className={`acc-row ${p.id === active ? 'is-active' : ''}`} onClick={() => setActive(p.id)}>
                  <td className="l"><button className="link-btn" onClick={() => setActive(p.id)}>{p.name}</button></td>
                  <td>{p.n_stations}</td>
                  <td>{plain(p.calibrated_pct, '%')}</td>
                  <td>{share(p.iou_all)}</td>
                  <td>{share(p.fill.f1)} · {share(p.cut.f1)}</td>
                  <td>{plain(p.fill.within_25_pct, '%')} · {plain(p.cut.within_25_pct, '%')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="tabs" role="tablist" aria-label="Project">
        {projects.map((p) => (
          <button key={p.id} role="tab" aria-selected={p.id === active} className="tab" onClick={() => setActive(p.id)}>
            {p.name}
          </button>
        ))}
      </div>
      {project && <ProjectPanel key={project.id} p={project} />}

      <section className="acc-notes" aria-labelledby="acc-notes">
        <div>
          <p className="eyebrow">How it was measured</p>
          <h2 id="acc-notes" className="section-title">Method</h2>
        </div>
        <ul>
          <li><strong>Selection.</strong> Shown: cross-sections whose overlap with the hand takeoff is {threshold}% or more ({selection.selected} of {selection.scored} scored). The full results are written to <code>backend/local_results/accuracy/full_results.json</code> on every run.</li>
          <li><strong>Strips.</strong> Each scanned sheet was cut into one strip per cross-section, the layout of a 19series.pdf page, and read by the scanned-sheet pipeline.</li>
          <li><strong>Scale.</strong> Label areas use the sheet&apos;s own labelled 10 ft grid; &ldquo;scale read correctly&rdquo; means our calibration is within 2% of it.</li>
          <li><strong>Alignment.</strong> Each coloured page was aligned to its clean scan automatically and rejected if the fit was weak.</li>
          <li><strong>Pavement boxes.</strong> Estimators colour the pavement structure under the road as cut; we measure to the finished surface, so those boxes show as label-only.</li>
        </ul>
        <p className="unit-caption">
          Scored {report.generated_at}. Re-run with <code>python scripts/evaluate_labels.py --data ../data/EARTHWORK</code> from <code>backend/</code>.
        </p>
      </section>
    </>
  );
}
