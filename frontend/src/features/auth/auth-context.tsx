/* eslint-disable react-refresh/only-export-components */
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from 'react'

import { setAuthFailureHandler } from '@/lib/api/client'
import { clearTokens, getStoredTokens, saveTokens, type StoredTokens } from '@/lib/auth/token-store'
import * as session from '@/lib/auth/session'
import { resolveErrorMessage } from '@/shared/lib/error'
import type { CurrentUser, Role } from '@/types/api'

interface AuthContextValue {
  user: CurrentUser | null
  tokens: StoredTokens | null
  isInitializing: boolean
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  hasAnyRole: (...roles: Role[]) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [tokens, setTokens] = useState<StoredTokens | null>(getStoredTokens())
  const [isInitializing, setIsInitializing] = useState(true)

  useEffect(() => {
    setAuthFailureHandler(() => {
      clearTokens()
      setTokens(null)
      setUser(null)
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    })
  }, [])

  useEffect(() => {
    const bootstrap = async () => {
      const savedTokens = getStoredTokens()
      if (!savedTokens) {
        setIsInitializing(false)
        return
      }

      try {
        const currentUser = await session.me()
        setTokens(savedTokens)
        setUser(currentUser)
      } catch {
        try {
          const refreshed = await session.refresh({ refresh_token: savedTokens.refreshToken })
          const nextTokens = {
            accessToken: refreshed.access_token,
            refreshToken: refreshed.refresh_token,
            expiresAt: refreshed.expires_at,
          }
          saveTokens(nextTokens)
          setTokens(nextTokens)
          const currentUser = await session.me()
          setUser(currentUser)
        } catch {
          clearTokens()
          setTokens(null)
          setUser(null)
        }
      } finally {
        setIsInitializing(false)
      }
    }

    void bootstrap()
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      tokens,
      isInitializing,
      isAuthenticated: Boolean(user),
      login: async (username, password) => {
        const response = await session.login({ username, password })
        const nextTokens = {
          accessToken: response.access_token,
          refreshToken: response.refresh_token,
          expiresAt: response.expires_at,
        }
        saveTokens(nextTokens)
        setTokens(nextTokens)

        try {
          const currentUser = await session.me()
          setUser(currentUser)
        } catch (error) {
          clearTokens()
          setTokens(null)
          setUser(null)
          throw new Error(resolveErrorMessage(error))
        }
      },
      logout: async () => {
        try {
          if (tokens?.refreshToken) {
            await session.logout(tokens.refreshToken)
          }
        } finally {
          clearTokens()
          setTokens(null)
          setUser(null)
        }
      },
      hasAnyRole: (...roles: Role[]) => {
        if (!user) {
          return false
        }
        return roles.includes(user.role)
      },
    }),
    [user, tokens, isInitializing],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
