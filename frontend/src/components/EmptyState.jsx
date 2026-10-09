import SectionGraphic from './SectionGraphic';

const COPY = {
  planSet: {
    eyebrow: 'Full plan set',
    title: <>Drop in a plan set. <em>Get the earthwork.</em></>,
    body: 'Every page is read. Cross-section sheets are found by their station labels, split into sections, traced, and grouped into roads with average-end-area volumes.',
    steps: [
      ['Detect', 'Finds cross-section pages and splits each into stations.'],
      ['Trace', 'Follows existing ground and the proposed template through the grid.'],
      ['Measure', 'Sums fill and cut per station, then volume per road in cubic yards.'],
    ],
  },
  sheets: {
    eyebrow: 'Scanned sheets',
    title: <>Pick the sheets. <em>See every square foot.</em></>,
    body: 'For scanned 19-series cross-sections. Each page is calibrated from its own grid and elevation labels, then measured cell by cell.',
    steps: [
      ['Calibrate', 'Reads the grid pitch and OCRs the elevation gutter for the datum.'],
      ['Trace', 'Separates dashed ground from the solid template and traces both.'],
      ['Ledger', 'Breaks fill and cut into 10 ft grid cells you can audit.'],
    ],
  },
};

export default function EmptyState({ mode }) {
  const c = COPY[mode];
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-copy">
        <p className="eyebrow">{c.eyebrow}</p>
        <h2 id="hero-title" className="hero-title">{c.title}</h2>
        <p className="hero-body">{c.body}</p>
      </div>

      <figure className="hero-figure">
        <SectionGraphic />
        <figcaption className="legend">
          <span><i className="swatch swatch-ground" />Existing ground</span>
          <span><i className="swatch swatch-design" />Proposed</span>
          <span><i className="swatch swatch-fill" />Fill</span>
          <span><i className="swatch swatch-cut" />Cut</span>
        </figcaption>
      </figure>

      <ol className="steps">
        {c.steps.map(([title, text], i) => (
          <li key={title} className="step">
            <span className="step-num">{String(i + 1).padStart(2, '0')}</span>
            <span className="step-title">{title}</span>
            <span className="step-text">{text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
