import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) return <p className="loading-state">Loading…</p>
  if (!isAuthenticated) return <Navigate to="/login" replace />

  return <Outlet />
}
