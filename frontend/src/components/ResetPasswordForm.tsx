import { Alert, Button, Card, CardDescription, CardTitle, Field, Input } from 'ice-ds'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { confirmPasswordReset } from '../api/auth'
import { extractErrorMessage } from '../api/client'

export function ResetPasswordForm({ resetKey }: { resetKey: string }) {
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isDone, setIsDone] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await confirmPasswordReset(resetKey, password, passwordConfirm)
      setIsDone(true)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isDone) {
    return (
      <Card className="auth-card" elevation="lg">
        <CardTitle>Password updated</CardTitle>
        <CardDescription>You can now sign in with your new password.</CardDescription>
        <p className="auth-switch">
          <Link to="/login">Go to sign in</Link>
        </p>
      </Card>
    )
  }

  return (
    <Card className="auth-card" elevation="lg">
      <CardTitle>Set a new password</CardTitle>
      <form className="form-stack" onSubmit={handleSubmit}>
        <Field label="New password" htmlFor="password" required>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        <Field label="Confirm new password" htmlFor="password_confirm" required>
          <Input
            id="password_confirm"
            name="password_confirm"
            type="password"
            autoComplete="new-password"
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
            required
          />
        </Field>

        {error && <Alert intent="error">{error}</Alert>}

        <div className="form-actions">
          <Button type="submit" fullWidth loading={isSubmitting}>
            Update password
          </Button>
        </div>
      </form>
    </Card>
  )
}
