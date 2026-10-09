import { useEffect, useState } from 'react';
import UploadPanel from './components/UploadPanel';
import RoadCard from './components/RoadCard';
import ResultCard from './components/ResultCard';
import VolumeSummaryTable from './components/VolumeSummaryTable';
import TickRule from './components/TickRule';
import { checkHealth, fetchPresets, processPdf, processPlanSet } from './api';

const EMPTY_TEXT = {
  planSet: {
    title: 'No plan set read yet',
    body: "Upload a full plan set PDF. Cross-section pages are found automatically, split by station, grouped by road, and each road's fill/cut volume is computed here.",
    loading: 'Scanning pages, tracing surfaces, computing volume…',
    error: 'Could not read this plan set',
  },
  sheets: {
    title: 'No sheets read yet',
    body: 'Upload a scanned cross-section PDF and pick pages to see the coloured fill / cut overlay and per-cell quantities here.',
    loading: 'Tracing ground and design surfaces…',
    error: 'Could not read this sheet set',
  },
};

export default function App() {
  const [mode, setMode] = useState('planSet');
  const [presets, setPresets] = useState(['19series']);
  const [depsOk, setDepsOk] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    checkHealth().then((h) => setDepsOk(h.ok)).catch(() => setDepsOk(false));
    fetchPresets().then((p) => setPresets(p.presets)).catch(() => {});
  }, []);

  function handleModeChange(next) {
    if (next === mode || isRunning) return;
    setMode(next);
    setResult(null);
    setError(null);
  }

  async function handleSubmit({ file, pages, preset }) {
    setIsRunning(true);
    setError(null);
    try {
      const body = mode === 'planSet'
        ? await processPlanSet({ file, preset })
        : await processPdf({ file, pages, preset });
      setResult(body);
    } catch (e) {
      setError(e.message);
      setResult(null);
    } finally {
      setIsRunning(false);
    }
  }

  const text = EMPTY_TEXT[mode];

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

      <main className="main-area">
        <TickRule count={60} labelEvery={10} />

        {!result && !isRunning && !error && (
          <div className="empty-state">
            <p className="empty-title">{text.title}</p>
            <p className="empty-body">{text.body}</p>
          </div>
        )}

        {isRunning && (
          <div className="loading-state">
            <div className="loading-sweep" />
            <p>{text.loading}</p>
          </div>
        )}

        {error && (
          <div className="error-state">
            <p className="error-title">{text.error}</p>
            <p className="error-body">{error}</p>
          </div>
        )}

        {result && !isRunning && mode === 'planSet' && (
          <>
            <p className="scan-summary">
              Scanned {result.pages_scanned} page{result.pages_scanned === 1 ? '' : 's'} &middot;{' '}
              {result.cross_section_pages} identified as cross-sections &middot;{' '}
              {result.roads.length} road{result.roads.length === 1 ? '' : 's'} found &middot;{' '}
              {result.timing.total_seconds.toFixed(1)}s total
              ({result.timing.avg_seconds_per_region.toFixed(2)}s/region avg)
            </p>
            {result.skipped_regions.length > 0 && (
              <div className="warning-strip" style={{ marginBottom: 20 }}>
                {result.skipped_regions.map((s, i) => <p key={i}>{s}</p>)}
              </div>
            )}
            <div style={{ marginBottom: 26 }}>
              <VolumeSummaryTable roads={result.roads} />
            </div>
            <div className="results-list">
              {result.roads.map((r, i) => <RoadCard key={r.road_label} road={r} index={i} />)}
            </div>
          </>
        )}

        {result && !isRunning && mode === 'sheets' && (
          <div className="results-list">
            {result.pages.map((r, i) => <ResultCard key={r.page} result={r} index={i} />)}
          </div>
        )}
      </main>
    </div>
  );
}
