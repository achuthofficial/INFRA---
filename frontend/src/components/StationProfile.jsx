import { useState } from 'react';
import { num } from '../lib/format';

// Fill (up) and cut (down) area at every station of one road, on one shared
// scale -- the shape of the earthwork along the corridor at a glance.
export default function StationProfile({ stations, openLabels, onSelect }) {
  const [hover, setHover] = useState(null);
  const n = stations.length;
  if (n === 0) return null;

  const maxFill = Math.max(...stations.map((s) => s.fill_ft2), 0);
  const maxCut = Math.max(...stations.map((s) => s.cut_ft2), 0);
  const H = 100;
  const pad = 6;
  const span = maxFill + maxCut;
  const scale = span > 0 ? (H - 2 * pad) / span : 0;
  const mid = span > 0 ? pad + maxFill * scale : H / 2;
  const band = 10;
  const bar = n > 60 ? 7 : 6;

  const active = hover != null ? stations[hover] : null;
  const ticks = n > 2 ? [0, Math.floor((n - 1) / 2), n - 1] : [...Array(n).keys()];

  return (
    <div className="profile">
      <div className="profile-readout" aria-live="polite">
        {active ? (
          <>
            <span className="profile-sta">STA {active.station_label}</span>
            <span>page {active.page_number}</span>
            <span className="t-fill">fill {num(active.fill_ft2)} ft²</span>
            <span className="t-cut">cut {num(active.cut_ft2)} ft²</span>
          </>
        ) : (
          <span className="profile-hint">Hover a bar to inspect a station. Click to open its overlay.</span>
        )}
      </div>

      <svg
        className="profile-chart"
        viewBox={`0 0 ${n * band} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Fill and cut area at ${n} stations, from ${stations[0].station_label} to ${stations[n - 1].station_label}`}
        onMouseLeave={() => setHover(null)}
      >
        <line x1="0" x2={n * band} y1={mid} y2={mid} className="profile-axis" />
        {stations.map((s, i) => {
          const x = i * band + (band - bar) / 2;
          const fh = s.fill_ft2 * scale;
          const ch = s.cut_ft2 * scale;
          const isOpen = openLabels[s.station_label];
          const dim = hover != null && hover !== i;
          return (
            <g key={`${s.station_label}-${i}`} className={`profile-col ${dim ? 'is-dim' : ''} ${isOpen ? 'is-open' : ''}`}>
              {isOpen && <rect x={i * band} y="0" width={band} height={H} className="profile-open" />}
              {fh > 0 && <rect x={x} y={mid - fh} width={bar} height={fh} className="profile-fill" />}
              {ch > 0 && <rect x={x} y={mid} width={bar} height={ch} className="profile-cut" />}
              <rect
                x={i * band} y="0" width={band} height={H}
                className="profile-hit"
                onMouseEnter={() => setHover(i)}
                onClick={() => onSelect(s.station_label)}
              />
            </g>
          );
        })}
      </svg>

      <div className="profile-ticks" aria-hidden="true">
        {ticks.map((i) => (
          <span key={i} style={{ left: `${((i + 0.5) / n) * 100}%` }}>{stations[i].station_label}</span>
        ))}
      </div>
    </div>
  );
}
