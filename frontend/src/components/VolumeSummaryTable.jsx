function csvEscape(value) {
  const str = String(value);
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

function pageFor(road, stationLabel) {
  const s = road.stations.find((st) => st.station_label === stationLabel);
  return s ? s.page_number : '';
}

function buildCSV(roads) {
  const header = ['Road', 'Road Flags', 'From', 'From Page', 'To', 'To Page', 'Length (ft)', 'Fill (cy)', 'Cut (cy)', 'Net (cy)', 'Warning'];
  const rows = [header];
  for (const r of roads) {
    const roadFlags = r.flags.join(' | ');
    for (const s of r.volume_segments) {
      rows.push([
        r.road_label, roadFlags, s.from, pageFor(r, s.from), s.to, pageFor(r, s.to),
        s.length_ft, s.fill_cy, s.cut_cy, s.net_cy, s.warning || '',
      ]);
    }
    rows.push([r.road_label, roadFlags, 'TOTAL', '', '', '', '', r.total_fill_cy, r.total_cut_cy, r.total_net_cy, '']);
  }
  return rows.map((row) => row.map(csvEscape).join(',')).join('\r\n');
}

function downloadCSV(roads) {
  const csv = buildCSV(roads);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'earthwork_volumes.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function VolumeSummaryTable({ roads }) {
  const grandFill = roads.reduce((sum, r) => sum + r.total_fill_cy, 0);
  const grandCut = roads.reduce((sum, r) => sum + r.total_cut_cy, 0);
  const grandNet = grandFill - grandCut;

  return (
    <div className="summary-card">
      <div className="summary-header">
        <span className="stamp-label">VOLUME SUMMARY</span>
        <button className="csv-button" onClick={() => downloadCSV(roads)}>
          Download CSV
        </button>
      </div>
      <table className="ledger-table summary-table">
        <thead>
          <tr>
            <th style={{ textAlign: 'left' }}>Road</th>
            <th>Stations</th>
            <th>Fill (cy)</th>
            <th>Cut (cy)</th>
            <th>Net (cy)</th>
          </tr>
        </thead>
        <tbody>
          {roads.map((r) => (
            <tr key={r.road_label}>
              <td style={{ textAlign: 'left' }}>{r.road_label}</td>
              <td>{r.stations.length}</td>
              <td>{r.total_fill_cy.toFixed(1)}</td>
              <td>{r.total_cut_cy.toFixed(1)}</td>
              <td className={r.total_net_cy >= 0 ? 'readout-fill' : 'readout-cut'}>
                {r.total_net_cy.toFixed(1)}
              </td>
            </tr>
          ))}
          <tr className="summary-total-row">
            <td style={{ textAlign: 'left' }}>All roads</td>
            <td></td>
            <td>{grandFill.toFixed(1)}</td>
            <td>{grandCut.toFixed(1)}</td>
            <td className={grandNet >= 0 ? 'readout-fill' : 'readout-cut'}>{grandNet.toFixed(1)}</td>
          </tr>
        </tbody>
      </table>
      <p className="unit-caption">
        Volumes in cubic yards (cy). CSV opens directly in Excel, or import it into an
        existing Google Sheet via File &rarr; Import &rarr; Upload.
      </p>
    </div>
  );
}
