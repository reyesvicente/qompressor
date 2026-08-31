import { ForgotPasswordForm } from '../components/ForgotPasswordForm'
import { Layout } from '../components/Layout'

export function ForgotPasswordPage() {
  return (
    <Layout>
      <main className="centered-page">
        <ForgotPasswordForm />
      </main>
    </Layout>
  )
}
