import { useState, useRef } from 'react';

export default function UploadPanel({ presets, mode, onModeChange, onSubmit, isRunning, depsOk }) {
  const [file, setFile] = useState(null);
  const [preset, setPreset] = useState(presets[0] || '19series');
  const [pages, setPages] = useState('1,2,3,20,70');
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const isPlanSet = mode === 'planSet';
  const canRun = file && !isRunning && (isPlanSet || pages.trim().length > 0);

  function handleFiles(files) {
    const f = files && files[0];
    if (f && f.name.toLowerCase().endsWith('.pdf')) setFile(f);
  }

  return (
    <aside className="rail">
      <div className="brand">
        <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
          <rect x="1" y="1" width="26" height="26" rx="3" fill="none" stroke="var(--brass-500)" strokeWidth="1.5" />
          <line x1="1" y1="9" x2="27" y2="9" stroke="var(--brass-500)" strokeWidth="1" opacity="0.6" />
          <line x1="1" y1="19" x2="27" y2="19" stroke="var(--brass-500)" strokeWidth="1" opacity="0.6" />
          <line x1="9" y1="1" x2="9" y2="27" stroke="var(--brass-500)" strokeWidth="1" opacity="0.6" />
          <line x1="19" y1="1" x2="19" y2="27" stroke="var(--brass-500)" strokeWidth="1" opacity="0.6" />
        </svg>
        <div>
          <h1>Earthwork Plan Reader</h1>
          <p className="brand-sub">Auto-detects cross-sections, groups by road, computes cut/fill volume</p>
        </div>
      </div>

      <section className="control-block">
        <span className="control-label">Mode</span>
        <div className="mode-toggle" role="group" aria-label="Processing mode">
          <button type="button" aria-pressed={isPlanSet} onClick={() => onModeChange('planSet')}>
            Full plan set
          </button>
          <button type="button" aria-pressed={!isPlanSet} onClick={() => onModeChange('sheets')}>
            Scanned sheets
          </button>
        </div>
      </section>

      <section className="control-block">
        <label className="control-label" htmlFor="pdf-drop">{isPlanSet ? 'Plan set PDF' : 'Cross-section PDF'}</label>
        <div
          id="pdf-drop"
          className={`dropzone ${dragOver ? 'dropzone-active' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click(); }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            hidden
            onChange={(e) => handleFiles(e.target.files)}
          />
          {file ? (
            <span className="drop-filename">{file.name}</span>
          ) : (
            <>
              <span className="drop-title">
                {isPlanSet ? 'Drop the full plan set or click to browse' : 'Drop PDF or click to browse'}
              </span>
              <span className="drop-hint">
                {isPlanSet
                  ? 'Every page is scanned automatically -- cover sheets, notes, and plan/profile pages are skipped on their own'
                  : 'Scanned 19-series / 23-series sheets, one cross-section per page'}
              </span>
            </>
          )}
        </div>
      </section>

      {!isPlanSet && (
        <section className="control-block">
          <label className="control-label" htmlFor="pages-input">Pages</label>
          <input
            id="pages-input"
            className="text-input"
            value={pages}
            onChange={(e) => setPages(e.target.value)}
            placeholder="1,2,3,20-25"
          />
          <span className="control-hint">Comma-separated, ranges allowed</span>
        </section>
      )}

      <section className="control-block">
        <label className="control-label" htmlFor="preset-select">Drawing series</label>
        <select
          id="preset-select"
          className="text-input"
          value={preset}
          onChange={(e) => setPreset(e.target.value)}
        >
          {presets.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </section>

      <button
        className="run-button"
        disabled={!canRun}
        onClick={() => onSubmit({ file, pages, preset })}
      >
        {isRunning ? (isPlanSet ? 'Reading plan set…' : 'Reading sheets…') : 'Run pipeline'}
      </button>

      <div className={`deps-indicator ${depsOk === false ? 'deps-bad' : ''}`}>
        <span className="deps-dot" />
        {depsOk === null ? 'Checking server…' : depsOk ? 'Server ready' : 'Server missing dependencies'}
      </div>
    </aside>
  );
}
