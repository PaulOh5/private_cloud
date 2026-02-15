import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RequireRole } from '@/features/auth/require-role'

const mockedUseAuth = vi.fn()

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: () => mockedUseAuth(),
}))

describe('RequireRole', () => {
  beforeEach(() => {
    mockedUseAuth.mockReset()
  })

  it('renders children when role is allowed', () => {
    mockedUseAuth.mockReturnValue({
      user: { id: 'u1', username: 'admin', role: 'admin', is_active: true },
      isInitializing: false,
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <RequireRole allow={['admin']}>
          <div>allowed</div>
        </RequireRole>
      </MemoryRouter>,
    )

    expect(screen.getByText('allowed')).toBeInTheDocument()
  })

  it('redirects when role is not allowed', () => {
    mockedUseAuth.mockReturnValue({
      user: { id: 'u2', username: 'viewer', role: 'viewer', is_active: true },
      isInitializing: false,
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="/"
            element={
              <RequireRole allow={['admin']}>
                <div>blocked</div>
              </RequireRole>
            }
          />
          <Route path="/unauthorized" element={<div>unauthorized</div>} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('unauthorized')).toBeInTheDocument()
  })
})
