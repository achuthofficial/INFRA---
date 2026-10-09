import { useState } from 'react';
import { num, signed } from '../lib/format';

export default function ResultCard({ result, index }) {
  const [showLedger, setShowLedger] = useState(false);
  const { page, fill_ft2, cut_ft2, net_ft2, cells, warnings, diagnostics, calibration, coloured_image_b64, ledger } = result;

  const calOk = calibration.squares_err < 0.02;
  const relative = diagnostics.datum_src.startsWith('relative');

  return (
    <article className="road-card sheet" style={{ animationDelay: `${index * 80}ms` }} aria-labelledby={`sheet-${page}`}>
      <header className="road-head">
        <span className="road-index">{String(page).padStart(3, '0')}</span>
        <div className="road-titles">
          <h3 id={`sheet-${page}`} className="road-title">Sheet {page}</h3>
          <p className="road-sub">
            <span className={`chip ${calOk ? 'chip-ok' : 'chip-warn'}`} title={`Axis span error ${calibration.squares_err} squares`}>
              {calOk ? 'Calibration OK' : 'Check calibration'}
            </span>
            <span className={`chip ${relative ? 'chip-warn' : 'chip-ok'}`} title={diagnostics.datum_src}>
              {relative ? 'Relative datum' : `Datum ${diagnostics.datum_src}`}
            </span>
            <span>{num(calibration.px_per_ft, 2)} px/ft</span>
          </p>
        </div>
        <div className="road-figures">
          <div><span className="fig-label">Fill</span><span className="fig-value t-fill">{num(fill_ft2)}</span></div>
          <div><span className="fig-label">Cut</span><span className="fig-value t-cut">{num(cut_ft2)}</span></div>
          <div><span className="fig-label">Net</span><span className="fig-value">{signed(net_ft2)}</span></div>
          <span className="fig-unit">square feet</span>
        </div>
      </header>

      <figure className="drawing">
        <img
          src={coloured_image_b64}
          alt={`Coloured fill/cut overlay for page ${page}: green regions are fill, red regions are cut`}
        />
      </figure>

      {warnings.length > 0 && (
        <div className="callout" role="note">
          <span className="callout-tag">Check</span>
          <div>{warnings.map((w, i) => <p key={i}>{w}</p>)}</div>
        </div>
      )}

      <div className="disclosure">
        <button className="disclosure-btn" onClick={() => setShowLedger((s) => !s)} aria-expanded={showLedger}>
          <span className={`chevron ${showLedger ? 'chevron-open' : ''}`} aria-hidden="true" />
          Cell ledger
          <span className="count">{cells} cells</span>
        </button>
        {showLedger && (
          <div className="table-wrap">
            <table className="data-table">
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
                    <td className="t-fill">{row.fill_ft2.toFixed(3)}</td>
                    <td className="t-cut">{row.cut_ft2.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </article>
  );
}
