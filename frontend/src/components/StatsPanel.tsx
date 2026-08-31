import { Stat, StatGrid } from 'ice-ds'
import type { BlobStats } from '../api/types'
import { formatBytes, formatRatio } from '../utils/format'

export function StatsPanel({ stats }: { stats: BlobStats | null }) {
  if (!stats) return null

  return (
    <StatGrid>
      <Stat label="Objects" value={stats.objects} />
      <Stat label="Logical size" value={formatBytes(stats.logical_bytes)} accent="blue" />
      <Stat label="Physical size" value={formatBytes(stats.physical_bytes)} accent="purple" />
      <Stat label="Effective ratio" value={formatRatio(stats.effective_ratio)} accent="green" />
      <Stat label="Bytes saved" value={formatBytes(stats.bytes_saved)} accent="green" />
    </StatGrid>
  )
}
