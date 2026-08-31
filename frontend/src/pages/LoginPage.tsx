import { Navigate } from 'react-router-dom'
import { LoginForm } from '../components/LoginForm'
import { Layout } from '../components/Layout'
import { useAuth } from '../hooks/useAuth'

export function LoginPage() {
  const { isAuthenticated } = useAuth()

  if (isAuthenticated) return <Navigate to="/dashboard" replace />

  return (
    <Layout>
      <main className="centered-page">
        <LoginForm />
      </main>
    </Layout>
  )
}
