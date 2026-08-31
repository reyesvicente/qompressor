import { Alert, Button, Card, CardDescription, CardTitle, Field, Input } from 'ice-ds'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { requestPasswordReset } from '../api/auth'
import { extractErrorMessage } from '../api/client'

export function ForgotPasswordForm() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSent, setIsSent] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await requestPasswordReset(email)
      setIsSent(true)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isSent) {
    return (
      <Card className="auth-card" elevation="lg">
        <CardTitle>Check your email</CardTitle>
        <CardDescription>
          If an account exists for {email}, we've sent a link to reset your password.
        </CardDescription>
        <p className="auth-switch">
          <Link to="/login">Back to sign in</Link>
        </p>
      </Card>
    )
  }

  return (
    <Card className="auth-card" elevation="lg">
      <CardTitle>Reset your password</CardTitle>
      <CardDescription>
        Enter the email on your account and we'll send you a reset link.
      </CardDescription>
      <form className="form-stack" onSubmit={handleSubmit}>
        <Field label="Email" htmlFor="email" required>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </Field>

        {error && <Alert intent="error">{error}</Alert>}

        <div className="form-actions">
          <Button type="submit" fullWidth loading={isSubmitting}>
            Send reset link
          </Button>
        </div>
      </form>
      <p className="auth-switch">
        <Link to="/login">Back to sign in</Link>
      </p>
    </Card>
  )
}
