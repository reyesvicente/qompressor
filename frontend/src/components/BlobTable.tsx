import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from 'ice-ds'
import { PackageOpen } from 'lucide-react'
import { useState } from 'react'
import { deleteBlob, downloadBlob } from '../api/blobs'
import { extractErrorMessage } from '../api/client'
import type { Blob as BlobRecord, BlobStatus } from '../api/types'
import { formatBytes, formatDate, formatPercent, formatRatio } from '../utils/format'

const STATUS_BADGE: Record<BlobStatus, 'success' | 'info' | 'error'> = {
  ready: 'success',
  running: 'info',
  pending: 'info',
  failed: 'error',
}

interface BlobTableProps {
  blobs: BlobRecord[]
  onDeleted: (id: string) => void
}

export function BlobTable({ blobs, onDeleted }: BlobTableProps) {
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleDownload(blob: BlobRecord) {
    setError(null)
    setBusyId(blob.id)
    try {
      await downloadBlob(blob.id, blob.name)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(blob: BlobRecord) {
    setError(null)
    setBusyId(blob.id)
    try {
      await deleteBlob(blob.id)
      onDeleted(blob.id)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  if (blobs.length === 0) {
    return (
      <EmptyState
        icon={<PackageOpen />}
        title="No objects yet"
        description="Upload a file to get started."
      />
    )
  }

  return (
    <>
      {error && <Alert intent="error">{error}</Alert>}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Policy</TableHead>
            <TableHead>Raw size</TableHead>
            <TableHead>Ratio</TableHead>
            <TableHead>Dedup rate</TableHead>
            <TableHead>Created</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {blobs.map((blob) => (
            <TableRow key={blob.id}>
              <TableCell>{blob.name}</TableCell>
              <TableCell>
                <Badge variant={STATUS_BADGE[blob.status]}>{blob.status}</Badge>
                {blob.status === 'failed' && blob.error && (
                  <span className="row-error" title={blob.error}>
                    {blob.error}
                  </span>
                )}
              </TableCell>
              <TableCell>{blob.policy}</TableCell>
              <TableCell>{formatBytes(blob.raw_size)}</TableCell>
              <TableCell>{formatRatio(blob.ratio)}</TableCell>
              <TableCell>{formatPercent(blob.dedup_rate)}</TableCell>
              <TableCell>{formatDate(blob.created_at)}</TableCell>
              <TableCell className="row-actions">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={blob.status !== 'ready' || busyId === blob.id}
                  onClick={() => handleDownload(blob)}
                >
                  Download
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busyId === blob.id}
                  onClick={() => handleDelete(blob)}
                >
                  Delete
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  )
}
