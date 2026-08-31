import { Navigate } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { SignupForm } from '../components/SignupForm'
import { useAuth } from '../hooks/useAuth'

export function SignupPage() {
  const { isAuthenticated } = useAuth()

  if (isAuthenticated) return <Navigate to="/dashboard" replace />

  return (
    <Layout>
      <main className="centered-page">
        <SignupForm />
      </main>
    </Layout>
  )
}
