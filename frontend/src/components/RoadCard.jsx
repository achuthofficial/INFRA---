import { useState } from 'react';

function cy(v) {
  return v.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export default function RoadCard({ road, index }) {
  const [expanded, setExpanded] = useState({});
  const { road_label, road_name, flags, stations, volume_segments, total_fill_cy, total_cut_cy, total_net_cy } = road;
  const netIsFill = total_net_cy >= 0;

  function toggle(label) {
    setExpanded((e) => ({ ...e, [label]: !e[label] }));
  }

  return (
    <article className="sheet-card" style={{ animationDelay: `${index * 60}ms` }}>
      <header className="sheet-stamp">
        <span className="stamp-label">ROAD</span>
        <span className="stamp-number">{road_label.toUpperCase()}</span>
        {road_name && road_name !== 'unknown' && <span className="datum-chip">{road_name}</span>}
        <span className="datum-chip">
          {stations.length > 0 ? `${stations[0].station_label} \u2192 ${stations[stations.length - 1].station_label}` : ''}
        </span>
      </header>

      {flags.length > 0 && (
        <div className="warning-strip">
          {flags.map((f, i) => <p key={i}>{f}</p>)}
        </div>
      )}

      <div className="readouts">
        <div className="readout">
          <span className="readout-label">Total fill (cy)</span>
          <span className="readout-value readout-fill">{cy(total_fill_cy)}</span>
        </div>
        <div className="readout">
          <span className="readout-label">Total cut (cy)</span>
          <span className="readout-value readout-cut">{cy(total_cut_cy)}</span>
        </div>
        <div className="readout">
          <span className="readout-label">Net (cy)</span>
          <span className={`readout-value ${netIsFill ? 'readout-fill' : 'readout-cut'}`}>
            {netIsFill ? '+' : ''}{cy(total_net_cy)}
          </span>
        </div>
        <div className="readout readout-muted">
          <span className="readout-label">Stations</span>
          <span className="readout-value">{stations.length}</span>
        </div>
      </div>

      <div className="ledger-table-wrap">
        <table className="ledger-table">
          <thead>
            <tr>
              <th>from</th><th>to</th><th>length (ft)</th><th>fill (cy)</th><th>cut (cy)</th><th>net (cy)</th><th></th>
            </tr>
          </thead>
          <tbody>
            {volume_segments.map((s, i) => (
              <tr key={i}>
                <td>{s.from}</td>
                <td>{s.to}</td>
                <td>{s.length_ft}</td>
                <td>{s.fill_cy.toFixed(1)}</td>
                <td>{s.cut_cy.toFixed(1)}</td>
                <td className={s.net_cy >= 0 ? 'readout-fill' : 'readout-cut'}>{s.net_cy.toFixed(1)}</td>
                <td>{s.warning ? <span className="row-flag" title={s.warning}>!</span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="unit-caption">All lengths in feet, all volumes in cubic yards (cy).</p>

      <div className="station-accordion">
        <p className="accordion-title">Cross-sections in this road ({stations.length})</p>
        {stations.map((s) => {
          const isOpen = !!expanded[s.station_label];
          return (
            <div key={s.station_label} className="accordion-item">
              <button
                className="accordion-header"
                onClick={() => toggle(s.station_label)}
                aria-expanded={isOpen}
              >
                <span className={`chevron ${isOpen ? 'chevron-open' : ''}`}>&#9656;</span>
                <span className="thumb-station">{s.station_label}</span>
                <span className="accordion-page">page {s.page_number}</span>
                <span className="readout-fill" style={{ marginLeft: 'auto' }}>{s.fill_ft2.toFixed(1)} ft²</span>
                <span className="readout-cut">{s.cut_ft2.toFixed(1)} ft²</span>
              </button>
              {isOpen && (
                <div className="accordion-body">
                  {s.coloured_image_b64 ? (
                    <img
                      src={s.coloured_image_b64}
                      alt={`Fill/cut overlay at station ${s.station_label}, page ${s.page_number}: green is fill, red is cut`}
                    />
                  ) : (
                    <p className="accordion-empty">No overlay image available for this station.</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </article>
  );
}
