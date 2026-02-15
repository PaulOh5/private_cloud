import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'

import { clearTokens, getStoredTokens, saveTokens } from '@/lib/auth/token-store'
import type { TokenResponse } from '@/types/api'

export const publicApiClient = axios.create({
  baseURL: '/api',
})

export const apiClient = axios.create({
  baseURL: '/api',
})

type RetryConfig = InternalAxiosRequestConfig & {
  _retry?: boolean
  _skipAuthRefresh?: boolean
}

let refreshPromise: Promise<string | null> | null = null
let authFailureHandler: (() => void) | null = null

export function setAuthFailureHandler(handler: () => void) {
  authFailureHandler = handler
}

async function refreshAccessToken(): Promise<string | null> {
  const tokens = getStoredTokens()
  if (!tokens?.refreshToken) {
    return null
  }

  const response = await publicApiClient.post<TokenResponse>('/auth/refresh', {
    refresh_token: tokens.refreshToken,
  })

  saveTokens({
    accessToken: response.data.access_token,
    refreshToken: response.data.refresh_token,
    expiresAt: response.data.expires_at,
  })

  return response.data.access_token
}

apiClient.interceptors.request.use((config) => {
  const tokens = getStoredTokens()

  if (tokens?.accessToken) {
    if (!config.headers) {
      config.headers = new AxiosHeaders()
    }
    config.headers.set('Authorization', `Bearer ${tokens.accessToken}`)
  }

  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryConfig | undefined
    const status = error.response?.status

    if (!config || config._skipAuthRefresh || status !== 401 || config._retry) {
      return Promise.reject(error)
    }

    config._retry = true

    if (!refreshPromise) {
      refreshPromise = refreshAccessToken()
        .catch(() => null)
        .finally(() => {
          refreshPromise = null
        })
    }

    const nextAccessToken = await refreshPromise
    if (!nextAccessToken) {
      clearTokens()
      authFailureHandler?.()
      return Promise.reject(error)
    }

    if (!config.headers) {
      config.headers = new AxiosHeaders()
    }
    config.headers.set('Authorization', `Bearer ${nextAccessToken}`)

    return apiClient(config)
  },
)
