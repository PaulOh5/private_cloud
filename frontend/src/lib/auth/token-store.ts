const TOKEN_STORAGE_KEY = 'private_cloud.auth.tokens'

export interface StoredTokens {
  accessToken: string
  refreshToken: string
  expiresAt: string
}

function canUseStorage() {
  return typeof window !== 'undefined' && typeof localStorage !== 'undefined'
}

export function getStoredTokens(): StoredTokens | null {
  if (!canUseStorage()) {
    return null
  }

  const raw = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as Partial<StoredTokens>
    if (!parsed.accessToken || !parsed.refreshToken || !parsed.expiresAt) {
      return null
    }
    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken,
      expiresAt: parsed.expiresAt,
    }
  } catch {
    return null
  }
}

export function saveTokens(tokens: StoredTokens): void {
  if (!canUseStorage()) {
    return
  }

  localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens))
}

export function clearTokens(): void {
  if (!canUseStorage()) {
    return
  }

  localStorage.removeItem(TOKEN_STORAGE_KEY)
}
