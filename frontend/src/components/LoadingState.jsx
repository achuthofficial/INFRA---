import { useEffect, useState } from 'react';
import SectionGraphic from './SectionGraphic';

const STAGES = {
  planSet: ['Scanning pages for station labels', 'Splitting sheets into cross-sections', 'Tracing ground and template', 'Grouping roads and computing volume'],
  sheets: ['Extracting page images', 'Calibrating grid and datum', 'Tracing ground and template', 'Building the cell ledger'],
};

function clock(s) {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

export default function LoadingState({ mode, fileName }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <section className="loading" aria-live="polite" aria-busy="true">
      <SectionGraphic scanning />
      <div className="loading-meta">
        <p className="eyebrow">Processing</p>
        <p className="loading-file">{fileName}</p>
        <p className="loading-clock" aria-label={`Elapsed ${elapsed} seconds`}>{clock(elapsed)}</p>
      </div>
      <ul className="loading-stages">
        {STAGES[mode].map((s) => <li key={s}>{s}</li>)}
      </ul>
      <p className="loading-note">
        {mode === 'planSet'
          ? 'Large plan sets take a minute or two — every page is read.'
          : 'Each sheet takes a few seconds; OCR of the elevation labels is the slow part.'}
      </p>
    </section>
  );
}
