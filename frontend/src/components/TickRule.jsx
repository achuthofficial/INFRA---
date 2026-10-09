export default function TickRule({ labelEvery = 5, count = 40 }) {
  const ticks = Array.from({ length: count + 1 }, (_, i) => i);
  return (
    <div className="tick-rule" role="presentation" aria-hidden="true">
      {ticks.map((i) => (
        <div key={i} className={`tick ${i % labelEvery === 0 ? 'tick-major' : ''}`}>
          {i % labelEvery === 0 && <span className="tick-label">{i * 10}</span>}
        </div>
      ))}
    </div>
  );
}
