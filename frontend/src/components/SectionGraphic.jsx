// A stylised road cross-section: dashed existing ground, solid proposed
// template, fill (design above ground) in green and cut (design below
// ground) in red -- the same reading the pipeline does on a real sheet.

const GROUND = '0,120 80,128 160,150 240,160 300,150 360,120 440,95 520,92 600,100';
const DESIGN = '134.2,142.9 200,110 300,106 400,110 416,118 463.8,94.1';
const FILL = '134.2,142.9 200,110 300,106 392.9,109.7 360,120 300,150 240,160 160,150';
const CUT = '392.9,109.7 400,110 416,118 463.8,94.1 440,95';

export default function SectionGraphic({ scanning = false, className = '' }) {
  return (
    <svg
      className={`section-graphic ${scanning ? 'is-scanning' : ''} ${className}`}
      viewBox="0 0 600 220"
      role="img"
      aria-label="Illustration of a road cross-section: fill shown in green where the proposed road sits above existing ground, cut shown in red where it sits below"
    >
      <defs>
        <pattern id="sg-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" className="sg-grid-line" />
        </pattern>
        <clipPath id="sg-reveal">
          <rect className="sg-reveal-rect" x="0" y="0" width="600" height="220" />
        </clipPath>
      </defs>

      <rect width="600" height="220" fill="url(#sg-grid)" />
      <line x1="300" y1="20" x2="300" y2="200" className="sg-centerline" />

      <g clipPath="url(#sg-reveal)">
        <polygon points={FILL} className="sg-fill" />
        <polygon points={CUT} className="sg-cut" />
        <polyline points={GROUND} className="sg-ground" />
        <polyline points={DESIGN} className="sg-design" />
      </g>

      <g className="sg-labels" aria-hidden="true">
        <text x="236" y="136">FILL</text>
        <text x="418" y="88">CUT</text>
        <text x="300" y="16" textAnchor="middle">℄</text>
      </g>

      {scanning && <line x1="0" y1="10" x2="0" y2="210" className="sg-scan" />}
    </svg>
  );
}
