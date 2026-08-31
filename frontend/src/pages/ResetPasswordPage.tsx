import { Alert } from 'ice-ds'
import { useParams } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { ResetPasswordForm } from '../components/ResetPasswordForm'

export function ResetPasswordPage() {
  const { key } = useParams<{ key: string }>()

  return (
    <Layout>
      <main className="centered-page">
        {key ? (
          <ResetPasswordForm resetKey={key} />
        ) : (
          <Alert intent="error" title="Invalid link">
            This password reset link is missing its key.
          </Alert>
        )}
      </main>
    </Layout>
  )
}
