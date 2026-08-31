import { Alert, Button, Card, CardTitle, Field, Input } from 'ice-ds'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { extractErrorMessage } from '../api/client'
import { useAuth } from '../hooks/useAuth'

export function LoginForm() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login(username, password)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="auth-card" elevation="lg">
      <CardTitle>Sign in</CardTitle>
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
        <Field label="Password" htmlFor="password" required>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>

        {error && <Alert intent="error">{error}</Alert>}

        <p className="auth-forgot">
          <Link to="/forgot-password">Forgot your password?</Link>
        </p>

        <div className="form-actions">
          <Button type="submit" fullWidth loading={isSubmitting}>
            Sign in
          </Button>
        </div>
      </form>
      <p className="auth-switch">
        Don't have an account? <Link to="/signup">Sign up</Link>
      </p>
    </Card>
  )
}
