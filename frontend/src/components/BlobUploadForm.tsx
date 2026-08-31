import { Alert, Button, Card, CardTitle, Field, Input, Progress, Select } from 'ice-ds'
import { useRef, useState, type FormEvent } from 'react'
import { uploadBlob } from '../api/blobs'
import { extractErrorMessage } from '../api/client'
import type { Blob as BlobRecord, BlobPolicy } from '../api/types'

const POLICIES: BlobPolicy[] = ['fast', 'balanced', 'archival']

export function BlobUploadForm({ onUploaded }: { onUploaded: (blob: BlobRecord) => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [corpusKey, setCorpusKey] = useState('')
  const [policy, setPolicy] = useState<BlobPolicy>('balanced')
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const file = fileInputRef.current?.files?.[0]
    if (!file) {
      setError('Choose a file to upload.')
      return
    }
    setError(null)
    setProgress(0)
    try {
      const blob = await uploadBlob({
        file,
        corpus_key: corpusKey || undefined,
        policy,
        onProgress: setProgress,
      })
      onUploaded(blob)
      if (fileInputRef.current) fileInputRef.current.value = ''
      setCorpusKey('')
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setProgress(null)
    }
  }

  return (
    <Card className="upload-card" elevation="md">
      <CardTitle>Upload</CardTitle>
      <form className="form-stack" onSubmit={handleSubmit}>
        <Field label="File" htmlFor="file" required>
          <Input id="file" name="file" type="file" ref={fileInputRef} required />
        </Field>

        <Field label="Corpus key" htmlFor="corpus_key" hint="e.g. orders.v1">
          <Input
            id="corpus_key"
            name="corpus_key"
            type="text"
            value={corpusKey}
            onChange={(e) => setCorpusKey(e.target.value)}
          />
        </Field>

        <Field label="Policy" htmlFor="policy">
          <Select
            id="policy"
            name="policy"
            value={policy}
            onChange={(e) => setPolicy(e.target.value as BlobPolicy)}
          >
            {POLICIES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        </Field>

        {error && <Alert intent="error">{error}</Alert>}
        {progress !== null && <Progress value={progress} label="Uploading" showValue />}

        <div className="form-actions">
          <Button type="submit" fullWidth disabled={progress !== null}>
            {progress !== null ? `Uploading… ${progress}%` : 'Upload'}
          </Button>
        </div>
      </form>
    </Card>
  )
}
