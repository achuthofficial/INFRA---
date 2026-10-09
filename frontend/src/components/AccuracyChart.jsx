import { useState } from 'react';
import { num } from '../lib/format';

// Per station: the human label as a hollow bar, the app as a solid bar
// inside it. Fill goes up, cut goes down, both on one shared scale.
export default function AccuracyChart({ stations }) {
  const [hover, setHover] = useState(null);
  const n = stations.length;
  if (n === 0) return null;

  const maxFill = Math.max(...stations.map((s) => Math.max(s.label_fill, s.app_fill)), 0);
  const maxCut = Math.max(...stations.map((s) => Math.max(s.label_cut, s.app_cut)), 0);
  const H = 100;
  const pad = 4;
  const span = maxFill + maxCut;
  const k = span > 0 ? (H - 2 * pad) / span : 0;
  const mid = span > 0 ? pad + maxFill * k : H / 2;
  const band = 10;
  const active = hover != null ? stations[hover] : null;

  return (
    <div className="profile acc-chart">
      <div className="profile-readout" aria-live="polite">
        {active ? (
          <>
            <span className="profile-sta">STA {active.station}{active.station_fixed ? ' (label corrected)' : ''}</span>
            <span>page {active.page}</span>
            <span className="t-fill">fill {num(active.app_fill)} / {num(active.label_fill)} ft²</span>
            <span className="t-cut">cut {num(active.app_cut)} / {num(active.label_cut)} ft²</span>
            <span>overlap {active.iou_all == null ? '–' : `${Math.round(active.iou_all * 100)}%`}</span>
          </>
        ) : (
          <span className="profile-hint">Hover a station: app / label area. Outline = human label, solid = app.</span>
        )}
      </div>
      <svg
        className="profile-chart"
        viewBox={`0 0 ${n * band} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`App versus hand-labelled fill and cut area at ${n} stations`}
        onMouseLeave={() => setHover(null)}
      >
        <line x1="0" x2={n * band} y1={mid} y2={mid} className="profile-axis" />
        {stations.map((s, i) => {
          const x = i * band;
          const dim = hover != null && hover !== i;
          return (
            <g key={`${s.page}-${s.station}`} className={`profile-col ${dim ? 'is-dim' : ''}`}>
              {s.label_fill > 0 && <rect x={x + 1} y={mid - s.label_fill * k} width={band - 2} height={s.label_fill * k} className="acc-label-fill" />}
              {s.label_cut > 0 && <rect x={x + 1} y={mid} width={band - 2} height={s.label_cut * k} className="acc-label-cut" />}
              {s.app_fill > 0 && <rect x={x + 3} y={mid - s.app_fill * k} width={band - 6} height={s.app_fill * k} className="profile-fill" />}
              {s.app_cut > 0 && <rect x={x + 3} y={mid} width={band - 6} height={s.app_cut * k} className="profile-cut" />}
              <rect x={x} y="0" width={band} height={H} className="profile-hit" onMouseEnter={() => setHover(i)} />
            </g>
          );
        })}
      </svg>
      <div className="profile-ticks" aria-hidden="true">
        <span style={{ left: 0 }}>{stations[0].station}</span>
        {n > 2 && <span style={{ left: '50%' }}>{stations[Math.floor((n - 1) / 2)].station}</span>}
        <span>{stations[n - 1].station}</span>
      </div>
    </div>
  );
}
