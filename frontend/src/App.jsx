import { useEffect, useState } from 'react';
import UploadPanel from './components/UploadPanel';
import EmptyState from './components/EmptyState';
import LoadingState from './components/LoadingState';
import KpiBand from './components/KpiBand';
import RoadCard from './components/RoadCard';
import ResultCard from './components/ResultCard';
import VolumeSummaryTable from './components/VolumeSummaryTable';
import TickRule from './components/TickRule';
import AccuracyView from './components/AccuracyView';
import { checkHealth, fetchPresets, processPdf, processPlanSet } from './api';
import { plural } from './lib/format';

const MODE_NAME = { planSet: 'Full plan set', sheets: 'Scanned sheets' };

function PlanSetResults({ result }) {
  const { roads, timing } = result;
  const fill = roads.reduce((s, r) => s + r.total_fill_cy, 0);
  const cut = roads.reduce((s, r) => s + r.total_cut_cy, 0);
  const stations = roads.reduce((s, r) => s + r.stations.length, 0);

  if (roads.length === 0) {
    return (
      <div className="notice">
        <p className="notice-title">No cross-section sheets found</p>
        <p>
          Read {plural(result.pages_scanned, 'page')} in {timing.total_seconds.toFixed(1)} s, but none had station
          labels and an offset axis readable from the PDF text. If this is a scanned drawing,
          switch to <strong>Scanned sheets</strong>.
        </p>
      </div>
    );
  }

  return (
    <>
      <KpiBand
        fill={fill}
        cut={cut}
        unit="cy"
        isVolume
        meta={[
          ['Pages scanned', result.pages_scanned.toLocaleString()],
          ['Cross-section pages', result.cross_section_pages.toLocaleString()],
          ['Roads', roads.length],
          ['Stations', stations.toLocaleString()],
          ['Run time', `${timing.total_seconds.toFixed(1)} s`],
        ]}
      />

      {result.skipped_regions.length > 0 && (
        <div className="callout callout-block" role="note">
          <span className="callout-tag">{plural(result.skipped_regions.length, 'region')} skipped</span>
          <div>{result.skipped_regions.map((s, i) => <p key={i}>{s}</p>)}</div>
        </div>
      )}

      <VolumeSummaryTable roads={roads} />
      <div className="section-head">
        <div>
          <p className="eyebrow">Corridors</p>
          <h2 className="section-title">Roads in this plan set</h2>
        </div>
      </div>
      <div className="results-list">
        {roads.map((r, i) => <RoadCard key={r.road_label} road={r} index={i} />)}
      </div>
    </>
  );
}

function SheetResults({ result }) {
  const { pages } = result;
  const fill = pages.reduce((s, p) => s + p.fill_ft2, 0);
  const cut = pages.reduce((s, p) => s + p.cut_ft2, 0);
  const warnings = pages.reduce((s, p) => s + p.warnings.length, 0);

  return (
    <>
      <KpiBand
        fill={fill}
        cut={cut}
        unit="ft²"
        meta={[
          ['Sheets', pages.length],
          ['Grid cells', pages.reduce((s, p) => s + p.cells, 0).toLocaleString()],
          ['Warnings', warnings],
          ['Preset', result.preset],
        ]}
        note="Totals are summed end areas across the selected sheets, not a volume."
      />
      <div className="section-head">
        <div>
          <p className="eyebrow">Sheets</p>
          <h2 className="section-title">Measured cross-sections</h2>
        </div>
      </div>
      <div className="results-list">
        {pages.map((r, i) => <ResultCard key={r.page} result={r} index={i} />)}
      </div>
    </>
  );
}

export default function App() {
  const [mode, setMode] = useState('planSet');
  const [presets, setPresets] = useState(['19series']);
  const [depsOk, setDepsOk] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [fileName, setFileName] = useState(null);
  const [view, setView] = useState('run');

  useEffect(() => {
    checkHealth().then((h) => setDepsOk(h.ok)).catch(() => setDepsOk(false));
    fetchPresets().then((p) => setPresets(p.presets)).catch(() => {});
  }, []);

  function reset() {
    setResult(null);
    setError(null);
  }

  function handleModeChange(next) {
    if (isRunning) return;
    setView('run');
    if (next === mode) return;
    setMode(next);
    reset();
  }

  async function handleSubmit({ file, pages, preset }) {
    setView('run');
    setIsRunning(true);
    setError(null);
    setFileName(file.name);
    try {
      const body = mode === 'planSet'
        ? await processPlanSet({ file, preset })
        : await processPdf({ file, pages, preset });
      setResult(body);
    } catch (e) {
      setError(e.message === 'Failed to fetch' ? 'Could not reach the server. Is the backend running on port 8811?' : e.message);
      setResult(null);
    } finally {
      setIsRunning(false);
    }
  }

  const showResult = result && !isRunning;

  return (
    <div className="app-shell">
      <UploadPanel
        presets={presets}
        mode={mode}
        onModeChange={handleModeChange}
        onSubmit={handleSubmit}
        isRunning={isRunning}
        depsOk={depsOk}
      />

      <main className="canvas">
        <TickRule count={48} labelEvery={8} />
        <header className="topbar">
          <nav className="view-switch" aria-label="View">
            <button aria-pressed={view === 'run'} onClick={() => setView('run')}>Run</button>
            <button aria-pressed={view === 'accuracy'} onClick={() => setView('accuracy')}>Accuracy</button>
          </nav>
          {view === 'run' ? (
            <p className="crumbs">
              <span className="crumb-current">{MODE_NAME[mode]}</span>
              {(showResult || isRunning) && fileName && (
                <>
                  <span aria-hidden="true">/</span>
                  <span className="crumb-file" title={fileName}>{fileName}</span>
                </>
              )}
            </p>
          ) : (
            <p className="crumbs"><span className="crumb-current">Scored against hand-coloured takeoffs</span></p>
          )}
          {view === 'run' && (showResult || error) && (
            <button className="btn-ghost" onClick={reset}>New run</button>
          )}
        </header>

        <div className="canvas-inner">
          {view === 'accuracy' ? <AccuracyView /> : (
            <>
              {!result && !isRunning && !error && <EmptyState mode={mode} />}

              {isRunning && <LoadingState mode={mode} fileName={fileName} />}

              {error && !isRunning && (
                <section className="error" role="alert">
                  <p className="eyebrow eyebrow-cut">Run failed</p>
                  <h2 className="hero-title">That drawing couldn&apos;t be read.</h2>
                  <p className="error-detail">{error}</p>
                  <p className="hero-body">Check the input type matches the PDF (vector plan set vs. scanned sheets), and for scanned sheets that the page numbers exist.</p>
                </section>
              )}

              {showResult && mode === 'planSet' && <PlanSetResults result={result} />}
              {showResult && mode === 'sheets' && <SheetResults result={result} />}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
