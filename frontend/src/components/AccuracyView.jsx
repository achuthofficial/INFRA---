import { useState } from 'react';
import report from '../data/accuracy.json';
import AccuracyChart from './AccuracyChart';
import { num, plural } from '../lib/format';

function pct(v) {
  if (v == null) return '–';
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`;
}

function grade(err) {
  if (err == null) return '';
  const a = Math.abs(err);
  return a <= 10 ? 'chip-ok' : a <= 25 ? 'chip-warn' : 'chip-bad';
}

function share(v) {
  return v == null ? '–' : `${Math.round(v * 100)}%`;
}

function plain(v, unit = '') {
  return v == null ? '–' : `${v}${unit}`;
}

const SERIES_COPY = {
  19: {
    tab: '19 series · staging',
    title: <>19-series staging sheets, <em>scored</em></>,
    body: 'Construction staging cross-sections (drawing numbers 19-xxxx). Each scanned sheet was cut into one strip per cross-section, the same layout as 19series.pdf, and read by the scanned-sheet pipeline.',
    scale: 'Label areas use the sheet’s own 10 ft grid, measured across the whole page; the offset and elevation numbers on every grid line confirm each square is 10 ft. The app calibrates each strip separately.',
    extra: [
      ['Staging annotations.', 'These sheets add traffic arrows, lane dimension boxes and temporary pavement strips. The app sometimes traces those as the road surface, which shows as blue (extra fill) in the comparisons.'],
      ['Station labels are read by OCR.', 'A misread digit that breaks the even station spacing is corrected from its neighbours and marked; stations that still can’t be read count for area but are left out of road volumes.'],
    ],
  },
  23: {
    tab: '23 series · earthwork',
    title: <>23-series earthwork sheets, <em>scored</em></>,
    body: 'Earthwork cross-sections (drawing numbers 23-xxxx). The clean copies are vector PDFs, read by the full plan-set pipeline exactly as the Run page does.',
    scale: 'Label areas use the true scale read from each sheet’s axis numbers in the PDF text, not the app’s calibration. Where the app reads the grid wrong, its own areas are off by the same factor.',
    extra: [
      ['Fine 1 ft grid.', 'Newer sheets draw a 1 ft grid under the 10 ft grid; the app reads the fine lines as 10 ft squares (Webb Creek), so its scale is about 10× off there.'],
    ],
  },
};

const METRIC_ROWS = [
  ['Total area error', (m) => pct(m.total_error_pct), 'Sum of app area vs sum of label area'],
  ['Median station error', (m) => plain(m.median_ape_pct, '%'), 'Typical |app − label| ÷ label for one station'],
  ['Stations within 10%', (m) => plain(m.within_10_pct, '%'), ''],
  ['Stations within 25%', (m) => plain(m.within_25_pct, '%'), ''],
  ['Bias per station', (m) => (m.bias_ft2 == null ? '–' : `${m.bias_ft2 > 0 ? '+' : ''}${m.bias_ft2} ft²`), 'Average app − label; + means the app over-reports'],
  ['RMSE per station', (m) => plain(m.rmse_ft2, ' ft²'), 'Root-mean-square area error'],
  ['Correlation (r)', (m) => plain(m.pearson_r), 'Do app and label rise and fall together across stations'],
  ['Pixel precision', (m) => share(m.precision), 'Of what the app coloured, how much the estimator also did'],
  ['Pixel recall', (m) => share(m.recall), 'Of what the estimator coloured, how much the app found'],
  ['F1 score', (m) => share(m.f1), 'Balance of precision and recall'],
  ['Mean overlap (IoU)', (m) => share(m.mean_iou), 'Per-station intersection over union'],
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
  const [open, setOpen] = useState(false);
  return (
    <section className="road-card acc-reliability" aria-labelledby="acc-rel">
      <header className="road-head">
        <div className="road-titles" style={{ gridColumn: '1 / 3' }}>
          <h3 id="acc-rel" className="road-title">{r.file}: reliability check</h3>
          <p className="road-sub">
            <span>No hand-coloured copy exists, so this checks what can be checked without one</span>
          </p>
        </div>
        <div className="road-figures">
          <div><span className="fig-label">Pages read</span><span className="fig-value">{r.processed}/{r.pages}</span></div>
          <div><span className="fig-label">Calibrated</span><span className="fig-value">{plain(r.calibrated_pct, '%')}</span></div>
          <div><span className="fig-label">Datum OCR</span><span className="fig-value">{plain(r.datum_ocr_pct, '%')}</span></div>
          <span className="fig-unit">scanned-sheet pipeline, as /api/process runs it</span>
        </div>
      </header>
      <dl className="acc-stats">
        <div><dt>Grid reads as 10 ft squares</dt><dd>{plain(r.ten_ft_grid_pct, '%')} of pages</dd></div>
        <div><dt>Axis span is whole squares</dt><dd>{plain(r.calibrated_pct, '%')} of pages</dd></div>
        <div><dt>Elevation datum from OCR</dt><dd>{plain(r.datum_ocr_pct, '%')} of pages</dd></div>
        <div><dt>Surface gap warning (&gt; 5 ft)</dt><dd>{plain(r.gap_warning_pct, '%')} of pages</dd></div>
        <div><dt>Buried-service tail trimmed</dt><dd>{plain(r.trimmed_pct, '%')} of pages</dd></div>
        <div><dt>Total area measured</dt><dd>fill {num(r.total_fill_ft2, 0)} · cut {num(r.total_cut_ft2, 0)} ft²</dd></div>
      </dl>
      {r.failures.length > 0 && (
        <div className="disclosure">
          <button className="disclosure-btn" onClick={() => setOpen((s) => !s)} aria-expanded={open}>
            <span className={`chevron ${open ? 'chevron-open' : ''}`} aria-hidden="true" />
            Pages that failed
            <span className="count count-warn">{r.failed}</span>
          </button>
          {open && <ul className="acc-issues">{r.failures.map((s, i) => <li key={i}>{s}</li>)}</ul>}
        </div>
      )}
    </section>
  );
}

function ProjectPanel({ p }) {
  const [showIssues, setShowIssues] = useState(false);
  const issues = [...p.align_failed, ...p.skipped];
  const fixed = p.stations.filter((s) => s.station_fixed).length;

  return (
    <article className="road-card acc-project" aria-labelledby={`acc-${p.id}`}>
      <header className="road-head">
        <div className="road-titles" style={{ gridColumn: '1 / 3' }}>
          <h3 id={`acc-${p.id}`} className="road-title">{p.name}</h3>
          <p className="road-sub">
            {p.drawing && <span>{p.drawing}</span>}
            <span>{plural(p.n_stations, 'station')} scored</span>
            <span>{p.pages_labeled} labelled of {p.pages_total} pages</span>
            {issues.length > 0 && <span>{issues.length} not scored</span>}
          </p>
        </div>
        <div className="road-figures">
          <div><span className="fig-label">Fill err</span><span className="fig-value t-fill">{pct(p.fill.total_error_pct)}</span></div>
          <div><span className="fig-label">Cut err</span><span className="fig-value t-cut">{pct(p.cut.total_error_pct)}</span></div>
          <div><span className="fig-label">Overlap</span><span className="fig-value">{share(p.iou_all)}</span></div>
          <span className="fig-unit">vs. hand-coloured takeoff</span>
        </div>
      </header>

      <dl className="acc-stats">
        <div><dt>Fill area · app / label</dt><dd>{num(p.fill.app_total, 0)} / {num(p.fill.label_total, 0)} ft²</dd></div>
        <div><dt>Cut area · app / label</dt><dd>{num(p.cut.app_total, 0)} / {num(p.cut.label_total, 0)} ft²</dd></div>
        <div><dt>Median station error</dt><dd>fill {plain(p.fill.median_ape_pct, '%')} · cut {plain(p.cut.median_ape_pct, '%')}</dd></div>
        <div><dt>F1 (pixel)</dt><dd>fill {share(p.fill.f1)} · cut {share(p.cut.f1)}</dd></div>
        <div><dt>Precision / recall</dt><dd>fill {share(p.fill.precision)} / {share(p.fill.recall)} · cut {share(p.cut.precision)} / {share(p.cut.recall)}</dd></div>
        <div><dt>Scale read correctly</dt><dd>{plain(p.calibrated_pct, '%')} of stations</dd></div>
        {fixed > 0 && <div><dt>Station labels corrected</dt><dd>{fixed} of {p.n_stations}</dd></div>}
      </dl>

      <AccuracyChart stations={p.stations} />

      {p.roads.length > 0 && (
        <div className="table-wrap acc-roads">
          <table className="data-table">
            <thead>
              <tr>
                <th className="l">Road / stations</th>
                <th>Fill cy app</th><th>Fill cy label</th><th>Error</th>
                <th>Cut cy app</th><th>Cut cy label</th><th>Error</th>
              </tr>
            </thead>
            <tbody>
              {p.roads.map((r) => (
                <tr key={r.road}>
                  <td className="l">
                    <span className="cell-strong">{r.first} → {r.last}</span>
                    <span className="cell-sub">{r.road} · {r.stations} stations</span>
                  </td>
                  <td className="t-fill">{num(r.app_fill_cy)}</td>
                  <td>{num(r.label_fill_cy)}</td>
                  <td><span className={`chip ${grade(r.fill_error_pct)}`}>{pct(r.fill_error_pct)}</span></td>
                  <td className="t-cut">{num(r.app_cut_cy)}</td>
                  <td>{num(r.label_cut_cy)}</td>
                  <td><span className={`chip ${grade(r.cut_error_pct)}`}>{pct(r.cut_error_pct)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {p.examples.length > 0 && (
        <div className="acc-examples">
          <p className="stations-title">Station comparisons</p>
          <div className="acc-grid">
            {p.examples.map((e) => (
              <figure key={e.image} className="acc-example">
                <img src={e.image} alt={`Comparison at station ${e.station}: app versus hand label`} loading="lazy" />
                <figcaption>
                  <span className={`chip ${e.kind === 'Best' ? 'chip-ok' : e.kind === 'Worst' ? 'chip-bad' : 'chip-warn'}`}>{e.kind}</span>
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
            <span><i className="swatch swatch-missed" />Label only (missed)</span>
            <span><i className="swatch swatch-extra" />App only (extra)</span>
          </p>
        </div>
      )}

      {issues.length > 0 && (
        <div className="disclosure">
          <button className="disclosure-btn" onClick={() => setShowIssues((s) => !s)} aria-expanded={showIssues}>
            <span className={`chevron ${showIssues ? 'chevron-open' : ''}`} aria-hidden="true" />
            Stations not scored
            <span className="count count-warn">{issues.length}</span>
          </button>
          {showIssues && (
            <ul className="acc-issues">
              {issues.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}

function SeriesReport({ series }) {
  const { overall, projects } = series;
  const copy = SERIES_COPY[series.id] ?? SERIES_COPY[23];
  const [active, setActive] = useState(projects[0]?.id);
  const project = projects.find((p) => p.id === active);

  return (
    <>
      <section className="acc-hero" aria-labelledby="acc-title">
        <p className="eyebrow">Validation · {series.pipeline}</p>
        <h2 id="acc-title" className="hero-title">{copy.title}</h2>
        <p className="hero-body">
          {copy.body} {plural(overall.n_stations, 'cross-section')} across{' '}
          {plural(projects.length, 'project')} compared with copies an estimator coloured by hand.
        </p>
      </section>

      <section className="kpi-band" aria-label="Overall accuracy">
        <div className="kpi-grid">
          <div className="kpi kpi-fill">
            <span className="kpi-label">Fill area error</span>
            <span className="kpi-value">{pct(overall.fill.total_error_pct)}</span>
            <span className="kpi-hint">{num(overall.fill.app_total, 0)} vs {num(overall.fill.label_total, 0)} ft² labelled · F1 {share(overall.fill.f1)}</span>
          </div>
          <div className="kpi kpi-cut">
            <span className="kpi-label">Cut area error</span>
            <span className="kpi-value">{pct(overall.cut.total_error_pct)}</span>
            <span className="kpi-hint">{num(overall.cut.app_total, 0)} vs {num(overall.cut.label_total, 0)} ft² labelled · F1 {share(overall.cut.f1)}</span>
          </div>
          <div className="kpi kpi-net">
            <span className="kpi-label">Overlap (IoU)</span>
            <span className="kpi-value">{share(overall.iou_all)}</span>
            <span className="kpi-hint">share of coloured area both agree on</span>
          </div>
        </div>
        <dl className="kpi-meta">
          <div><dt>Cross-sections scored</dt><dd>{overall.n_stations} <small className="muted-dark">of {overall.sections_found} found ({plain(overall.scored_pct, '%')})</small></dd></div>
          <div><dt>Scale read correctly</dt><dd>{plain(overall.calibrated_pct, '%')} of stations</dd></div>
          <div><dt>Median station error</dt><dd>fill {plain(overall.fill.median_ape_pct, '%')} · cut {plain(overall.cut.median_ape_pct, '%')}</dd></div>
          <div><dt>Within 25%</dt><dd>fill {plain(overall.fill.within_25_pct, '%')} · cut {plain(overall.cut.within_25_pct, '%')}</dd></div>
        </dl>
        <p className="kpi-note">
          Error = (app − label) ÷ label, on total area. Station error is the median of |app − label| ÷ label over
          stations with at least {report.min_area_ft2} ft² labelled.
        </p>
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

      {series.reliability && <Reliability r={series.reliability} />}

      <section aria-labelledby="acc-projects">
        <div className="section-head" style={{ marginBottom: 18 }}>
          <div>
            <p className="eyebrow">By project</p>
            <h2 id="acc-projects" className="section-title">Where it holds up, and where it doesn&apos;t</h2>
          </div>
        </div>
        <div className="table-wrap table-wrap-flat">
          <table className="data-table summary-table">
            <thead>
              <tr>
                <th className="l">Project</th><th>Stations</th><th>Scale OK</th>
                <th>Fill error</th><th>Cut error</th><th>F1 fill · cut</th><th>Overlap</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className={`acc-row ${p.id === active ? 'is-active' : ''}`} onClick={() => setActive(p.id)}>
                  <td className="l"><button className="link-btn" onClick={() => setActive(p.id)}>{p.name}</button></td>
                  <td>{p.n_stations}</td>
                  <td>{plain(p.calibrated_pct, '%')}</td>
                  <td><span className={`chip ${grade(p.fill.total_error_pct)}`}>{pct(p.fill.total_error_pct)}</span></td>
                  <td><span className={`chip ${grade(p.cut.total_error_pct)}`}>{pct(p.cut.total_error_pct)}</span></td>
                  <td>{share(p.fill.f1)} · {share(p.cut.f1)}</td>
                  <td>{share(p.iou_all)}</td>
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
          <p className="eyebrow">Read this before trusting the numbers</p>
          <h2 id="acc-notes" className="section-title">What the score does and doesn&apos;t mean</h2>
        </div>
        <ul>
          <li><strong>Scale.</strong> {copy.scale} &ldquo;Scale read correctly&rdquo; means the app is within 2% of it.</li>
          <li><strong>Pavement boxes.</strong> Estimators colour the pavement structure under the road as cut. The app measures to the finished surface only, so it under-reports cut there by design. That shows as amber under the road in the comparisons.</li>
          {copy.extra.map(([t, d]) => <li key={t}><strong>{t}</strong> {d}</li>)}
          <li><strong>Hand-colouring is approximate.</strong> Edges drawn by hand differ by a few pixels, so a few percent of disagreement is noise, not error.</li>
          <li><strong>Only coloured pages count.</strong> Pages with no colour at all were skipped rather than treated as zero earthwork, and each page was aligned to its clean copy automatically and rejected if the fit was weak.</li>
          {series.not_scored.map((n) => (
            <li key={n.name}><strong>Not scored: {n.name}.</strong> {n.reason}</li>
          ))}
        </ul>
        <p className="unit-caption">
          Scored {report.generated_at}. Re-run with <code>python scripts/evaluate_labels.py --data ../data/EARTHWORK</code> from <code>backend/</code>.
        </p>
      </section>
    </>
  );
}

export default function AccuracyView() {
  const [sid, setSid] = useState(report.series[0]?.id);
  const series = report.series.find((s) => s.id === sid);

  return (
    <>
      <div className="tabs series-tabs" role="tablist" aria-label="Sheet series">
        {report.series.map((s) => (
          <button key={s.id} role="tab" aria-selected={s.id === sid} className="tab" onClick={() => setSid(s.id)}>
            {(SERIES_COPY[s.id] ?? { tab: s.name }).tab}
          </button>
        ))}
      </div>
      {series && <SeriesReport key={series.id} series={series} />}
    </>
  );
}
