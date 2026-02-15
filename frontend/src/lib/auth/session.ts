import { apiClient, publicApiClient } from '@/lib/api/client'
import type { CurrentUser, LoginRequest, RefreshTokenRequest, TokenResponse } from '@/types/api'

export async function login(request: LoginRequest): Promise<TokenResponse> {
  const response = await publicApiClient.post<TokenResponse>('/auth/login', request)
  return response.data
}

export async function refresh(request: RefreshTokenRequest): Promise<TokenResponse> {
  const response = await publicApiClient.post<TokenResponse>('/auth/refresh', request)
  return response.data
}

export async function me(): Promise<CurrentUser> {
  const response = await apiClient.get<CurrentUser>('/auth/me')
  return response.data
}

export async function logout(refreshToken: string): Promise<void> {
  await apiClient.post(
    '/auth/logout',
    { refresh_token: refreshToken },
    {
      _skipAuthRefresh: true,
    },
  )
}
