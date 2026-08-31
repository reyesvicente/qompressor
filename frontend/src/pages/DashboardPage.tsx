import { Alert, Spinner } from 'ice-ds'
import { useCallback, useEffect, useState } from 'react'
import { getStats, listBlobs } from '../api/blobs'
import { extractErrorMessage } from '../api/client'
import type { Blob as BlobRecord, BlobStats } from '../api/types'
import { BlobTable } from '../components/BlobTable'
import { BlobUploadForm } from '../components/BlobUploadForm'
import { Layout } from '../components/Layout'
import { StatsPanel } from '../components/StatsPanel'
import { useAuth } from '../hooks/useAuth'

export function DashboardPage() {
  const { user } = useAuth()
  const [blobs, setBlobs] = useState<BlobRecord[]>([])
  const [stats, setStats] = useState<BlobStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const refresh = useCallback(() => {
    return Promise.all([listBlobs(), getStats()])
      .then(([blobList, blobStats]) => {
        setBlobs(blobList)
        setStats(blobStats)
        setError(null)
      })
      .catch((err) => setError(extractErrorMessage(err)))
      .finally(() => setIsLoading(false))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const hasInFlightBlobs = blobs.some(
    (blob) => blob.status === 'pending' || blob.status === 'running',
  )

  useEffect(() => {
    if (!hasInFlightBlobs) return
    const interval = setInterval(refresh, 3000)
    return () => clearInterval(interval)
  }, [hasInFlightBlobs, refresh])

  function handleUploaded(blob: BlobRecord) {
    setBlobs((prev) => [blob, ...prev])
    refresh()
  }

  function handleDeleted(id: string) {
    setBlobs((prev) => prev.filter((blob) => blob.id !== id))
    refresh()
  }

  return (
    <Layout>
      <main className="dashboard page-container">
        <header className="dashboard-header">
          <div>
            <h1>Objects</h1>
            <p>Welcome back, {user?.name || user?.username}.</p>
          </div>
        </header>

        {error && <Alert intent="error">{error}</Alert>}

        <StatsPanel stats={stats} />

        <div className="dashboard-section">
          <BlobUploadForm onUploaded={handleUploaded} />
        </div>

        <div className="dashboard-section">
          {isLoading ? <Spinner label="Loading…" /> : (
            <BlobTable blobs={blobs} onDeleted={handleDeleted} />
          )}
        </div>
      </main>
    </Layout>
  )
}
