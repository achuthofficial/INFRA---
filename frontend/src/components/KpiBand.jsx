import { num, signed } from '../lib/format';

// Headline totals plus a cut/fill balance bar. `unit` is "cy" for plan-set
// volumes and "ft²" for scanned-sheet areas.
export default function KpiBand({ fill, cut, unit, meta, note, isVolume = false }) {
  const net = fill - cut;
  const total = fill + cut;
  const fillPct = total > 0 ? (fill / total) * 100 : 50;
  // Borrow / surplus only means something for volumes, not summed end areas.
  const balance = !isVolume ? null
    : Math.abs(net) < 0.05 * Math.max(total, 1) ? 'Roughly balanced'
    : net > 0 ? 'Net fill — borrow needed' : 'Net cut — surplus to haul';

  return (
    <section className="kpi-band" aria-label="Totals">
      <div className="kpi-grid">
        <div className="kpi kpi-fill">
          <span className="kpi-label">Fill</span>
          <span className="kpi-value">{num(fill)}<small>{unit}</small></span>
        </div>
        <div className="kpi kpi-cut">
          <span className="kpi-label">Cut</span>
          <span className="kpi-value">{num(cut)}<small>{unit}</small></span>
        </div>
        <div className="kpi kpi-net">
          <span className="kpi-label">Net</span>
          <span className="kpi-value">{signed(net)}<small>{unit}</small></span>
          {balance && <span className="kpi-hint">{balance}</span>}
        </div>
      </div>

      {total > 0 && (
        <div className="balance" role="img" aria-label={`Fill ${fillPct.toFixed(0)} percent, cut ${(100 - fillPct).toFixed(0)} percent of moved material`}>
          <div className="balance-bar">
            <span className="balance-fill" style={{ width: `${fillPct}%` }} />
            <span className="balance-cut" style={{ width: `${100 - fillPct}%` }} />
          </div>
          <div className="balance-scale">
            <span>{fillPct.toFixed(0)}% fill</span>
            <span>{(100 - fillPct).toFixed(0)}% cut</span>
          </div>
        </div>
      )}

      {meta && (
        <dl className="kpi-meta">
          {meta.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {note && <p className="kpi-note">{note}</p>}
    </section>
  );
}
