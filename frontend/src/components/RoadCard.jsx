import { useState } from 'react';
import StationProfile from './StationProfile';
import { num, signed, plural } from '../lib/format';

export default function RoadCard({ road, index }) {
  const [expanded, setExpanded] = useState({});
  const [showSegments, setShowSegments] = useState(false);
  const {
    road_label, road_name, series_id, flags, stations, volume_segments,
    total_fill_cy, total_cut_cy, total_net_cy,
  } = road;
  const title = road_name && road_name !== 'unknown' ? road_name : road_label.replace('_', ' ');
  const maxArea = Math.max(...stations.map((s) => Math.max(s.fill_ft2, s.cut_ft2)), 1);
  const flagged = volume_segments.filter((s) => s.warning).length;
  const domId = (label) => `sta-${road_label}-${label.replace('+', '_')}`;

  function toggle(label) {
    setExpanded((e) => ({ ...e, [label]: !e[label] }));
  }

  function openFromChart(label) {
    setExpanded((e) => ({ ...e, [label]: true }));
    requestAnimationFrame(() => {
      document.getElementById(domId(label))?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  return (
    <article className="road-card" style={{ animationDelay: `${index * 80}ms` }} aria-labelledby={`${road_label}-title`}>
      <header className="road-head">
        <span className="road-index">{String(index + 1).padStart(2, '0')}</span>
        <div className="road-titles">
          <h3 id={`${road_label}-title`} className="road-title">{title}</h3>
          <p className="road-sub">
            {stations.length > 0 && <span>STA {stations[0].station_label} → {stations[stations.length - 1].station_label}</span>}
            <span>{plural(stations.length, 'station')}</span>
            {series_id && series_id !== 'unknown' && <span title="Sheet series (title-block .dgn file)">{series_id}</span>}
          </p>
        </div>
        <div className="road-figures">
          <div><span className="fig-label">Fill</span><span className="fig-value t-fill">{num(total_fill_cy)}</span></div>
          <div><span className="fig-label">Cut</span><span className="fig-value t-cut">{num(total_cut_cy)}</span></div>
          <div><span className="fig-label">Net</span><span className="fig-value">{signed(total_net_cy)}</span></div>
          <span className="fig-unit">cubic yards</span>
        </div>
      </header>

      {flags.length > 0 && (
        <div className="callout" role="note">
          <span className="callout-tag">Check</span>
          <div>{flags.map((f, i) => <p key={i}>{f}</p>)}</div>
        </div>
      )}

      <StationProfile stations={stations} openLabels={expanded} onSelect={openFromChart} />

      <div className="disclosure">
        <button
          className="disclosure-btn"
          onClick={() => setShowSegments((s) => !s)}
          aria-expanded={showSegments}
        >
          <span className={`chevron ${showSegments ? 'chevron-open' : ''}`} aria-hidden="true" />
          Volume segments
          <span className="count">{volume_segments.length}</span>
          {flagged > 0 && <span className="count count-warn">{flagged} flagged</span>}
        </button>
        {showSegments && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">From</th><th className="l">To</th><th>Length ft</th>
                  <th>Fill cy</th><th>Cut cy</th><th>Net cy</th><th aria-label="Warning" />
                </tr>
              </thead>
              <tbody>
                {volume_segments.map((s, i) => (
                  <tr key={i} className={s.warning ? 'row-warn' : ''}>
                    <td className="l">{s.from}</td>
                    <td className="l">{s.to}</td>
                    <td>{num(s.length_ft, 0)}</td>
                    <td className="t-fill">{num(s.fill_cy)}</td>
                    <td className="t-cut">{num(s.cut_cy)}</td>
                    <td>{signed(s.net_cy)}</td>
                    <td>{s.warning ? <span className="row-flag" title={s.warning} aria-label={s.warning}>!</span> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="stations">
        <p className="stations-title">Cross-sections</p>
        <ul className="station-list">
          {stations.map((s) => {
            const isOpen = !!expanded[s.station_label];
            return (
              <li key={s.station_label} id={domId(s.station_label)} className={`station ${isOpen ? 'is-open' : ''}`}>
                <button className="station-row" onClick={() => toggle(s.station_label)} aria-expanded={isOpen}>
                  <span className={`chevron ${isOpen ? 'chevron-open' : ''}`} aria-hidden="true" />
                  <span className="station-label">{s.station_label}</span>
                  <span className="station-page">p.{s.page_number}</span>
                  <span className="station-bars" aria-hidden="true">
                    <i className="mini-fill" style={{ width: `${(s.fill_ft2 / maxArea) * 100}%` }} />
                    <i className="mini-cut" style={{ width: `${(s.cut_ft2 / maxArea) * 100}%` }} />
                  </span>
                  <span className="station-num t-fill">{num(s.fill_ft2)}</span>
                  <span className="station-num t-cut">{num(s.cut_ft2)}</span>
                </button>
                {isOpen && (
                  <div className="station-body">
                    {s.coloured_image_b64 ? (
                      <img
                        src={s.coloured_image_b64}
                        alt={`Fill/cut overlay at station ${s.station_label}, page ${s.page_number}: green is fill, red is cut`}
                      />
                    ) : (
                      <p className="muted">No overlay image available for this station.</p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        <p className="unit-caption">Station areas in ft². Green = fill, red = cut.</p>
      </div>
    </article>
  );
}
