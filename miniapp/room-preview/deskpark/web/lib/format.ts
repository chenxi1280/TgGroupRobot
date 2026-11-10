export function formatChips(n: number): string {
  if (Math.abs(n) >= 100_000) return `${(n / 1000).toFixed(0)}k`;
  if (Math.abs(n) >= 10_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return n.toLocaleString('en-US');
}

export function signed(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}
