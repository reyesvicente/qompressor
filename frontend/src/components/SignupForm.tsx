import { Alert, Button, Card, CardTitle, Field, Input } from 'ice-ds'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { extractErrorMessage } from '../api/client'
import { useAuth } from '../hooks/useAuth'

export function SignupForm() {
  const { register } = useAuth()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await register({
        username,
        email,
        password,
        password_confirm: passwordConfirm,
      })
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="auth-card" elevation="lg">
      <CardTitle>Create an account</CardTitle>
      <form className="form-stack" onSubmit={handleSubmit}>
        <Field label="Username" htmlFor="username" required>
          <Input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </Field>
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
        <Field label="Password" htmlFor="password" required>
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
        <Field label="Confirm password" htmlFor="password_confirm" required>
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
            Sign up
          </Button>
        </div>
      </form>
      <p className="auth-switch">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </Card>
  )
}
