import { useState, useRef } from 'react';
import { fileSize } from '../lib/format';

const MODES = [
  { id: 'planSet', title: 'Full plan set', text: 'Vector PDF. Cross-sections found automatically.' },
  { id: 'sheets', title: 'Scanned sheets', text: 'Raster PDF. You choose the pages.' },
];

export default function UploadPanel({ presets, mode, onModeChange, onSubmit, isRunning, depsOk }) {
  const [file, setFile] = useState(null);
  const [rejected, setRejected] = useState(false);
  const [preset, setPreset] = useState(presets[0] || '19series');
  const [pages, setPages] = useState('1,2,3,20,70');
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const isPlanSet = mode === 'planSet';
  const pagesOk = isPlanSet || pages.trim().length > 0;
  const canRun = file && !isRunning && pagesOk;
  const blocker = !file ? 'Add a PDF to continue' : !pagesOk ? 'Enter the pages to read' : null;

  function handleFiles(files) {
    const f = files && files[0];
    if (!f) return;
    const ok = f.name.toLowerCase().endsWith('.pdf');
    setRejected(!ok);
    if (ok) setFile(f);
  }

  return (
    <aside className="rail" aria-label="Run settings">
      <div className="brand">
        <svg className="brand-mark" width="36" height="36" viewBox="0 0 36 36" aria-hidden="true">
          <rect x="0.75" y="0.75" width="34.5" height="34.5" rx="8" fill="none" stroke="currentColor" strokeOpacity="0.25" />
          <path d="M5 22 L11 21 L16 25 L22 24 L31 15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.5 2" strokeLinecap="round" />
          <path d="M8 21.5 L13 17 L23 17 L27 19.5" fill="none" stroke="var(--accent-on-dark)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div>
          <p className="brand-name">Earthwork</p>
          <p className="brand-sub">Plan reader · cut &amp; fill</p>
        </div>
      </div>

      <form
        className="rail-form"
        onSubmit={(e) => { e.preventDefault(); if (canRun) onSubmit({ file, pages, preset }); }}
      >
        <fieldset className="step-block">
          <legend className="step-legend"><span className="step-no">01</span>Input type</legend>
          <div className="mode-cards">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                className="mode-card"
                aria-pressed={mode === m.id}
                onClick={() => onModeChange(m.id)}
                disabled={isRunning}
              >
                <span className="mode-title">{m.title}</span>
                <span className="mode-text">{m.text}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="step-block">
          <legend className="step-legend"><span className="step-no">02</span>{isPlanSet ? 'Plan set PDF' : 'Cross-section PDF'}</legend>
          <div
            className={`dropzone ${dragOver ? 'is-over' : ''} ${file ? 'has-file' : ''}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
            role="button"
            tabIndex={0}
            aria-label={file ? `Selected ${file.name}. Press to choose a different PDF` : 'Choose a PDF file'}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inputRef.current?.click(); } }}
          >
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              hidden
              onChange={(e) => { handleFiles(e.target.files); e.target.value = ''; }}
            />
            {file ? (
              <>
                <span className="file-icon" aria-hidden="true">PDF</span>
                <span className="file-meta">
                  <span className="file-name">{file.name}</span>
                  <span className="file-size">{fileSize(file.size)} · click to replace</span>
                </span>
              </>
            ) : (
              <>
                <svg className="drop-icon" width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
                  <path d="M14 18V5M8.5 10.5 14 5l5.5 5.5M4 18v4.5A1.5 1.5 0 0 0 5.5 24h17a1.5 1.5 0 0 0 1.5-1.5V18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="drop-title">Drop a PDF here</span>
                <span className="drop-hint">or <u>browse your files</u></span>
              </>
            )}
          </div>
          {rejected && <p className="field-error" role="alert">That file isn&apos;t a PDF.</p>}
          <p className="field-hint">
            {isPlanSet
              ? 'Cover sheets, notes and plan/profile pages are skipped on their own.'
              : 'Scanned 19-series sheets, one cross-section per page.'}
          </p>
        </fieldset>

        <fieldset className="step-block">
          <legend className="step-legend"><span className="step-no">03</span>Settings</legend>
          {!isPlanSet && (
            <label className="field">
              <span className="field-label">Pages</span>
              <input
                className="text-input"
                value={pages}
                onChange={(e) => setPages(e.target.value)}
                placeholder="1,2,3,20-25"
                inputMode="numeric"
                spellCheck={false}
              />
              <span className="field-hint">Comma-separated; ranges like 20-25 work.</span>
            </label>
          )}
          <label className="field">
            <span className="field-label">Drawing series</span>
            <span className="select-wrap">
              <select className="text-input" value={preset} onChange={(e) => setPreset(e.target.value)}>
                {presets.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </span>
          </label>
        </fieldset>

        <div className="rail-footer">
          <button type="submit" className="run-button" disabled={!canRun}>
            <span>{isRunning ? 'Reading…' : isPlanSet ? 'Read plan set' : 'Read sheets'}</span>
            {!isRunning && (
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <path d="M3 9h12M10 4l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </button>
          {blocker && !isRunning && <p className="run-hint">{blocker}</p>}

          <p className={`server-status ${depsOk === false ? 'is-bad' : depsOk ? 'is-ok' : ''}`} role="status">
            <span className="status-dot" aria-hidden="true" />
            {depsOk === null ? 'Connecting to server…' : depsOk ? 'Server ready' : 'Server offline or missing poppler / tesseract'}
          </p>
        </div>
      </form>
    </aside>
  );
}
