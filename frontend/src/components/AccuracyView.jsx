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

function ProjectPanel({ p }) {
  const [showIssues, setShowIssues] = useState(false);
  const issues = [...p.align_failed, ...p.skipped];
  const scored = p.stations.length;

  return (
    <article className="road-card acc-project" aria-labelledby={`acc-${p.id}`}>
      <header className="road-head">
        <div className="road-titles" style={{ gridColumn: '1 / 3' }}>
          <h3 id={`acc-${p.id}`} className="road-title">{p.name}</h3>
          <p className="road-sub">
            <span>{plural(scored, 'station')} scored</span>
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
        <div><dt>Median station error</dt><dd>fill {p.fill.median_ape_pct ?? '–'}% · cut {p.cut.median_ape_pct ?? '–'}%</dd></div>
        <div><dt>Stations within 25%</dt><dd>fill {p.fill.within_25_pct ?? '–'}% · cut {p.cut.within_25_pct ?? '–'}%</dd></div>
        <div><dt>Scale read correctly</dt><dd>{p.calibrated_pct ?? '–'}% of stations</dd></div>
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

export default function AccuracyView() {
  const { overall, projects } = report;
  const [active, setActive] = useState(projects[0]?.id);
  const project = projects.find((p) => p.id === active);

  return (
    <>
      <section className="acc-hero" aria-labelledby="acc-title">
        <p className="eyebrow">Validation</p>
        <h2 id="acc-title" className="hero-title">How close is it to a <em>human takeoff?</em></h2>
        <p className="hero-body">
          The app was run on the clean plan sets and compared, cross-section by cross-section, with
          the copies an estimator coloured by hand. {plural(overall.stations, 'station')} across{' '}
          {plural(projects.length, 'project')} scored on {report.generated_at}.
        </p>
      </section>

      <section className="kpi-band" aria-label="Overall accuracy">
        <div className="kpi-grid">
          <div className="kpi kpi-fill">
            <span className="kpi-label">Fill area error</span>
            <span className="kpi-value">{pct(overall.fill.total_error_pct)}</span>
            <span className="kpi-hint">{num(overall.fill.app_total, 0)} vs {num(overall.fill.label_total, 0)} ft² labelled</span>
          </div>
          <div className="kpi kpi-cut">
            <span className="kpi-label">Cut area error</span>
            <span className="kpi-value">{pct(overall.cut.total_error_pct)}</span>
            <span className="kpi-hint">{num(overall.cut.app_total, 0)} vs {num(overall.cut.label_total, 0)} ft² labelled</span>
          </div>
          <div className="kpi kpi-net">
            <span className="kpi-label">Overlap (IoU)</span>
            <span className="kpi-value">{share(overall.iou_all)}</span>
            <span className="kpi-hint">share of coloured area both agree on</span>
          </div>
        </div>
        <dl className="kpi-meta">
          <div><dt>Stations scored</dt><dd>{overall.stations} <small className="muted-dark">+{overall.skipped} failed</small></dd></div>
          <div><dt>Scale read correctly</dt><dd>{overall.calibrated_pct}% of stations</dd></div>
          <div><dt>Median station error</dt><dd>fill {overall.fill.median_ape_pct}% · cut {overall.cut.median_ape_pct}%</dd></div>
          <div><dt>Within 10%</dt><dd>fill {overall.fill.within_10_pct}% · cut {overall.cut.within_10_pct}%</dd></div>
          <div><dt>Within 25%</dt><dd>fill {overall.fill.within_25_pct}% · cut {overall.cut.within_25_pct}%</dd></div>
        </dl>
        <p className="kpi-note">
          Error = (app − label) ÷ label, on total area. Station error is the median of |app − label| ÷ label over
          stations with at least {report.min_area_ft2} ft² labelled.
        </p>
      </section>

      <section aria-labelledby="acc-projects">
        <div className="section-head" style={{ marginBottom: 18 }}>
          <div>
            <p className="eyebrow">By project</p>
            <h2 id="acc-projects" className="section-title">Where it holds up, and where it doesn't</h2>
          </div>
        </div>
        <div className="table-wrap table-wrap-flat">
          <table className="data-table summary-table">
            <thead>
              <tr>
                <th className="l">Project</th><th>Stations</th><th>Scale OK</th>
                <th>Fill error</th><th>Cut error</th><th>Median station error</th><th>Overlap</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className={`acc-row ${p.id === active ? 'is-active' : ''}`} onClick={() => setActive(p.id)}>
                  <td className="l"><button className="link-btn" onClick={() => setActive(p.id)}>{p.name}</button></td>
                  <td>{p.stations.length}</td>
                  <td>{p.calibrated_pct ?? '–'}%</td>
                  <td><span className={`chip ${grade(p.fill.total_error_pct)}`}>{pct(p.fill.total_error_pct)}</span></td>
                  <td><span className={`chip ${grade(p.cut.total_error_pct)}`}>{pct(p.cut.total_error_pct)}</span></td>
                  <td>fill {p.fill.median_ape_pct ?? '–'}% · cut {p.cut.median_ape_pct ?? '–'}%</td>
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
          <h2 id="acc-notes" className="section-title">What the score does and doesn't mean</h2>
        </div>
        <ul>
          <li><strong>Scale.</strong> Label areas use the true scale read from each sheet&apos;s axis numbers, not the app&apos;s calibration. Where the app reads the grid wrong, its own areas are off by the same factor; &ldquo;Scale read correctly&rdquo; means within 2%.</li>
          <li><strong>Pavement boxes.</strong> Estimators colour the pavement structure under the road as cut. The app measures to the finished surface only, so it under-reports cut there by design. That shows as amber under the road in the comparisons.</li>
          <li><strong>Hand-colouring is approximate.</strong> Edges drawn by hand differ by a few pixels, so a few percent of disagreement is noise, not error.</li>
          <li><strong>Only coloured pages count.</strong> Pages with no colour at all were skipped rather than treated as zero earthwork.</li>
          <li><strong>Registration.</strong> The coloured copies are scans at a different page size; each page was aligned to its clean copy automatically and rejected if the fit was weak.</li>
          {report.not_scored.map((n) => (
            <li key={n.name}><strong>Not scored: {n.name}.</strong> {n.reason}</li>
          ))}
        </ul>
        <p className="unit-caption">Re-run with <code>python scripts/evaluate_labels.py --data ../data/EARTHWORK</code> from <code>backend/</code>.</p>
      </section>
    </>
  );
}
