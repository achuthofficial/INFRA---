import { useState } from 'react';

function num(v) {
  return v.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export default function ResultCard({ result, index }) {
  const [showLedger, setShowLedger] = useState(false);
  const { page, fill_ft2, cut_ft2, net_ft2, cells, warnings, diagnostics, calibration, coloured_image_b64, ledger } = result;

  const netIsFill = net_ft2 >= 0;
  const calOk = calibration.squares_err < 0.02;
  const datumShort = diagnostics.datum_src.startsWith('relative')
    ? 'relative datum'
    : diagnostics.datum_src;

  return (
    <article className="sheet-card" style={{ animationDelay: `${index * 60}ms` }}>
      <header className="sheet-stamp">
        <span className="stamp-label">SHEET</span>
        <span className="stamp-number">{String(page).padStart(3, '0')}</span>
        <span className={`cal-chip ${calOk ? 'cal-ok' : 'cal-warn'}`}>
          {calOk ? 'calibration ok' : 'calibration check'}
        </span>
        <span className="datum-chip" title={diagnostics.datum_src}>{datumShort}</span>
      </header>

      <img
        className="sheet-image"
        src={coloured_image_b64}
        alt={`Coloured fill/cut overlay for page ${page}: green regions are fill, red regions are cut`}
      />

      <div className="readouts">
        <div className="readout">
          <span className="readout-label">Fill</span>
          <span className="readout-value readout-fill">{num(fill_ft2)} ft²</span>
        </div>
        <div className="readout">
          <span className="readout-label">Cut</span>
          <span className="readout-value readout-cut">{num(cut_ft2)} ft²</span>
        </div>
        <div className="readout">
          <span className="readout-label">Net</span>
          <span className={`readout-value ${netIsFill ? 'readout-fill' : 'readout-cut'}`}>
            {netIsFill ? '+' : ''}{num(net_ft2)} ft²
          </span>
        </div>
        <div className="readout readout-muted">
          <span className="readout-label">Cells</span>
          <span className="readout-value">{cells}</span>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="warning-strip">
          {warnings.map((w, i) => <p key={i}>{w}</p>)}
        </div>
      )}

      <button className="ledger-toggle" onClick={() => setShowLedger((s) => !s)}>
        {showLedger ? 'Hide' : 'Show'} cell ledger ({ledger.length} rows)
      </button>

      {showLedger && (
        <div className="ledger-table-wrap">
          <table className="ledger-table">
            <thead>
              <tr>
                <th>x from</th><th>x to</th><th>elev top</th><th>elev bot</th><th>fill ft²</th><th>cut ft²</th>
              </tr>
            </thead>
            <tbody>
              {ledger.map((row, i) => (
                <tr key={i}>
                  <td>{row.x_from}</td>
                  <td>{row.x_to}</td>
                  <td>{row.elev_top}</td>
                  <td>{row.elev_bot}</td>
                  <td>{row.fill_ft2.toFixed(3)}</td>
                  <td>{row.cut_ft2.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
