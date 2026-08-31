import { apiClient } from './client'
import type { User } from './types'

interface TokenResponse {
  token: string
}

interface RegisterResponse {
  token: string
  user: User
}

export interface RegisterPayload {
  username: string
  email: string
  name?: string
  password: string
  password_confirm: string
}

export async function login(username: string, password: string): Promise<string> {
  const { data } = await apiClient.post<TokenResponse>('auth-token/', {
    username,
    password,
  })
  return data.token
}

export async function register(payload: RegisterPayload): Promise<RegisterResponse> {
  const { data } = await apiClient.post<RegisterResponse>('auth/register/', payload)
  return data
}

export async function requestPasswordReset(email: string): Promise<void> {
  await apiClient.post('auth/password/reset/', { email })
}

export async function confirmPasswordReset(
  key: string,
  password: string,
  passwordConfirm: string,
): Promise<void> {
  await apiClient.post('auth/password/reset/confirm/', {
    key,
    password,
    password_confirm: passwordConfirm,
  })
}

export async function confirmEmail(key: string): Promise<void> {
  await apiClient.post('auth/email/confirm/', { key })
}

export async function fetchMe(): Promise<User> {
  const { data } = await apiClient.get<User>('users/me/')
  return data
}

export async function updateProfile(
  username: string,
  patch: Partial<Pick<User, 'name'>>,
): Promise<User> {
  const { data } = await apiClient.patch<User>(`users/${username}/`, patch)
  return data
}
