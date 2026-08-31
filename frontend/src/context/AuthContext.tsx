import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  fetchMe,
  login as loginRequest,
  register as registerRequest,
  type RegisterPayload,
} from '../api/auth'
import { getStoredToken, setStoredToken, setUnauthorizedHandler } from '../api/client'
import type { User } from '../api/types'
import { AuthContext } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(() => !!getStoredToken())

  const logout = useCallback(() => {
    setStoredToken(null)
    setUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    return () => setUnauthorizedHandler(null)
  }, [logout])

  useEffect(() => {
    if (!getStoredToken()) return
    fetchMe()
      .then(setUser)
      .catch(() => setStoredToken(null))
      .finally(() => setIsLoading(false))
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const token = await loginRequest(username, password)
    setStoredToken(token)
    const me = await fetchMe()
    setUser(me)
  }, [])

  const register = useCallback(async (payload: RegisterPayload) => {
    const { token, user: registeredUser } = await registerRequest(payload)
    setStoredToken(token)
    setUser(registeredUser)
  }, [])

  const value = useMemo(
    () => ({ user, isAuthenticated: !!user, isLoading, login, register, logout }),
    [user, isLoading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
