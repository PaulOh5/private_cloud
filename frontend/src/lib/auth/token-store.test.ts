import { afterEach, describe, expect, it } from 'vitest'

import { clearTokens, getStoredTokens, saveTokens } from '@/lib/auth/token-store'

describe('token-store', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('saves and reads tokens', () => {
    saveTokens({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      expiresAt: '2099-01-01T00:00:00Z',
    })

    expect(getStoredTokens()).toEqual({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      expiresAt: '2099-01-01T00:00:00Z',
    })
  })

  it('clears tokens', () => {
    saveTokens({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      expiresAt: '2099-01-01T00:00:00Z',
    })

    clearTokens()

    expect(getStoredTokens()).toBeNull()
  })
})
