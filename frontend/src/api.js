const BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8811';

export async function checkHealth() {
  const res = await fetch(`${BASE}/api/health`);
  if (!res.ok) throw new Error(`health check failed: ${res.status}`);
  return res.json();
}

export async function fetchPresets() {
  const res = await fetch(`${BASE}/api/presets`);
  if (!res.ok) throw new Error(`could not load presets: ${res.status}`);
  return res.json();
}

async function postForm(path, form) {
  const res = await fetch(`${BASE}${path}`, { method: 'POST', body: form });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : `request failed (${res.status})`;
    throw new Error(detail);
  }
  return body;
}

export function processPlanSet({ file, preset }) {
  const form = new FormData();
  form.append('file', file);
  form.append('preset', preset);
  return postForm('/api/process_plan_set', form);
}

export function processPdf({ file, pages, preset }) {
  const form = new FormData();
  form.append('file', file);
  form.append('pages', pages);
  form.append('preset', preset);
  return postForm('/api/process', form);
}
