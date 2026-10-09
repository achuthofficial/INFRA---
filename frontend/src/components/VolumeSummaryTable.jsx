import { num, signed } from '../lib/format';

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
  const maxMoved = Math.max(...roads.map((r) => r.total_fill_cy + r.total_cut_cy), 1);

  return (
    <section className="summary" aria-labelledby="summary-title">
      <div className="section-head">
        <div>
          <p className="eyebrow">Schedule</p>
          <h2 id="summary-title" className="section-title">Volume by road</h2>
        </div>
        <button className="btn-ghost" onClick={() => downloadCSV(roads)}>
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <path d="M7 1v8M3.5 5.5 7 9l3.5-3.5M1.5 12.5h11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Download CSV
        </button>
      </div>
      <div className="table-wrap table-wrap-flat">
        <table className="data-table summary-table">
          <thead>
            <tr>
              <th className="l">Road</th>
              <th className="l bar-col">Fill / cut</th>
              <th>Stations</th>
              <th>Fill cy</th>
              <th>Cut cy</th>
              <th>Net cy</th>
            </tr>
          </thead>
          <tbody>
            {roads.map((r) => (
              <tr key={r.road_label}>
                <td className="l">
                  <span className="cell-strong">{r.road_name && r.road_name !== 'unknown' ? r.road_name : r.road_label}</span>
                  {r.road_name && r.road_name !== 'unknown' && <span className="cell-sub">{r.road_label}</span>}
                </td>
                <td className="l bar-col" aria-hidden="true">
                  <span className="share">
                    <i className="mini-fill" style={{ width: `${(r.total_fill_cy / maxMoved) * 100}%` }} />
                    <i className="mini-cut" style={{ width: `${(r.total_cut_cy / maxMoved) * 100}%` }} />
                  </span>
                </td>
                <td>{r.stations.length}</td>
                <td className="t-fill">{num(r.total_fill_cy)}</td>
                <td className="t-cut">{num(r.total_cut_cy)}</td>
                <td>{signed(r.total_net_cy)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="l">All roads</td>
              <td className="bar-col" />
              <td>{roads.reduce((n, r) => n + r.stations.length, 0)}</td>
              <td className="t-fill">{num(grandFill)}</td>
              <td className="t-cut">{num(grandCut)}</td>
              <td>{signed(grandNet)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="unit-caption">
        Average-end-area volumes in cubic yards, no shrink/swell applied. The CSV opens in Excel or
        Google Sheets (File &rarr; Import).
      </p>
    </section>
  );
}
