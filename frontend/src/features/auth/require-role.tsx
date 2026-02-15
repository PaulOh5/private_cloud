import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from '@/features/auth/auth-context'
import type { Role } from '@/types/api'

interface RequireRoleProps {
  allow: Role[]
  children: ReactNode
}

export function RequireRole({ allow, children }: RequireRoleProps) {
  const { user, isInitializing } = useAuth()

  if (isInitializing) {
    return null
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (!allow.includes(user.role)) {
    return <Navigate to="/unauthorized" replace />
  }

  return children
}
