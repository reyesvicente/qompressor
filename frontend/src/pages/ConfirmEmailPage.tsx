import { Alert, Card, CardTitle, Spinner } from 'ice-ds'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { confirmEmail } from '../api/auth'
import { extractErrorMessage } from '../api/client'
import { Layout } from '../components/Layout'

export function ConfirmEmailPage() {
  const { key } = useParams<{ key: string }>()
  const [status, setStatus] = useState<'pending' | 'success' | 'error'>(() =>
    key ? 'pending' : 'error',
  )
  const [error, setError] = useState<string | null>(() =>
    key ? null : 'This confirmation link is missing its key.',
  )

  useEffect(() => {
    if (!key) return
    confirmEmail(key)
      .then(() => setStatus('success'))
      .catch((err) => {
        setStatus('error')
        setError(extractErrorMessage(err))
      })
  }, [key])

  return (
    <Layout>
      <main className="centered-page">
        <Card className="auth-card" elevation="lg">
          <CardTitle>Email confirmation</CardTitle>
          {status === 'pending' && <Spinner label="Confirming…" />}
          {status === 'success' && (
            <>
              <Alert intent="success">Your email has been confirmed.</Alert>
              <p className="auth-switch">
                <Link to="/login">Continue to sign in</Link>
              </p>
            </>
          )}
          {status === 'error' && <Alert intent="error">{error}</Alert>}
        </Card>
      </main>
    </Layout>
  )
}
