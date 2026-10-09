export function num(v, digits = 1) {
  if (v == null || Number.isNaN(v)) return '–';
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function signed(v, digits = 1) {
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v), digits)}`;
}

export function fileSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function plural(n, word, many = `${word}s`) {
  return `${n.toLocaleString()} ${n === 1 ? word : many}`;
}
