import { apiClient } from './client'
import type { Blob as BlobRecord, BlobStats, UploadBlobParams } from './types'

export async function listBlobs(): Promise<BlobRecord[]> {
  const { data } = await apiClient.get<BlobRecord[]>('blobs/')
  return data
}

export async function getBlob(id: string): Promise<BlobRecord> {
  const { data } = await apiClient.get<BlobRecord>(`blobs/${id}/`)
  return data
}

export async function uploadBlob({
  file,
  name,
  corpus_key,
  policy,
  onProgress,
}: UploadBlobParams): Promise<BlobRecord> {
  const form = new FormData()
  form.append('file', file)
  if (name) form.append('name', name)
  if (corpus_key) form.append('corpus_key', corpus_key)
  if (policy) form.append('policy', policy)

  const { data } = await apiClient.post<BlobRecord>('blobs/upload/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event) => {
      if (onProgress && event.total) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    },
  })
  return data
}

export async function downloadBlob(id: string, filename: string): Promise<void> {
  const response = await apiClient.get(`blobs/${id}/download/`, {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(response.data as globalThis.Blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export async function deleteBlob(id: string): Promise<void> {
  await apiClient.delete(`blobs/${id}/`)
}

export async function getStats(): Promise<BlobStats> {
  const { data } = await apiClient.get<BlobStats>('blobs/stats/')
  return data
}
