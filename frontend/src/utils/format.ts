export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const sign = bytes < 0 ? '-' : ''
  const magnitude = Math.abs(bytes)
  // Decimal (SI) units, matching what OSes and file pickers report for file
  // size - 1 MB = 1000 * 1000 bytes, not 1024 * 1024.
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(
    Math.floor(Math.log(magnitude) / Math.log(1000)),
    units.length - 1,
  )
  const value = magnitude / 1000 ** exponent
  return `${sign}${value.toFixed(exponent === 0 ? 0 : 2)} ${units[exponent]}`
}

export function formatRatio(ratio: number | null): string {
  if (ratio === null || !Number.isFinite(ratio)) return '—'
  return `${ratio.toFixed(2)}x`
}

export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}
