export interface User {
  username: string
  name: string
  url: string
}

export type BlobPolicy = 'fast' | 'balanced' | 'archival'

export type BlobStatus = 'pending' | 'running' | 'ready' | 'failed'

export interface Blob {
  id: string
  name: string
  content_type: string
  corpus_key: string
  policy: BlobPolicy
  status: BlobStatus
  error: string
  raw_size: number
  stored_size: number
  logical_size: number
  chunk_count: number
  dedup_hits: number
  dedup_rate: number
  ratio: number
  marginal_ratio: number | null
  sha256: string
  encode_seconds: number
  created_at: string
  completed_at: string | null
}

export interface BlobStats {
  objects: number
  logical_bytes: number
  physical_bytes: number
  effective_ratio: number | null
  bytes_saved: number
}

export interface UploadBlobParams {
  file: File
  name?: string
  corpus_key?: string
  policy?: BlobPolicy
  onProgress?: (percent: number) => void
}

export interface ApiErrorBody {
  detail?: string
  [field: string]: unknown
}
