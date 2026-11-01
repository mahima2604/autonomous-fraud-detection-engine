// formatters.js — small display-formatting helpers shared across pages.

export function formatCurrency(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount ?? 0);
}

export function formatDate(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(isoString) {
  if (!isoString) return '—';
  const utcIsoString = typeof isoString === 'string' &&
    !/(Z|[+-]\d{2}:?\d{2})$/i.test(isoString)
      ? `${isoString}Z`
      : isoString;

  const date = new Date(utcIsoString);
  if (Number.isNaN(date.getTime())) return '—';

  return date.toLocaleString('en-IN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  });
}
