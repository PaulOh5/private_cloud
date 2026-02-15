import { Building2, LogOut, Menu, Server, ShieldCheck, SquareUserRound, Workflow } from 'lucide-react'
import { type ComponentType, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '@/features/auth/auth-context'
import { formatDateTime } from '@/shared/lib/date'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'

type NavItem = {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  roles: Array<'admin' | 'operator' | 'viewer'>
}

const navItems: NavItem[] = [
  { to: '/instances', label: '인스턴스', icon: Server, roles: ['admin', 'operator', 'viewer'] },
  { to: '/tasks', label: '작업 이력', icon: Workflow, roles: ['admin', 'operator', 'viewer'] },
  { to: '/users', label: '사용자 관리', icon: SquareUserRound, roles: ['admin'] },
  { to: '/tenants', label: 'Tenant 관리', icon: Building2, roles: ['admin'] },
  { to: '/audit-logs', label: '감사 로그', icon: ShieldCheck, roles: ['admin'] },
]

function Sidebar({ onClose }: { onClose?: () => void }) {
  const { user } = useAuth()

  return (
    <aside className="flex h-full w-72 flex-col border-r border-border bg-card/80 backdrop-blur-sm">
      <div className="border-b border-border px-6 py-5">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">Private Cloud</p>
        <h1 className="mt-2 text-xl font-semibold">운영 콘솔</h1>
      </div>
      <nav className="flex-1 px-3 py-4">
        {navItems
          .filter((item) => (user ? item.roles.includes(user.role) : false))
          .map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  'mb-1 flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
      </nav>
    </aside>
  )
}

export function ConsoleLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const { user, tokens, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const tokenSummary = tokens?.expiresAt ? `Access 만료 예정: ${formatDateTime(tokens.expiresAt)}` : '토큰 정보 없음'

  const onLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(circle_at_20%_20%,hsl(var(--primary)/0.18),transparent_40%),radial-gradient(circle_at_90%_10%,hsl(20_90%_60%/0.14),transparent_35%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.4))]" />
      <div className="mx-auto flex min-h-screen max-w-[1500px]">
        <div className="hidden lg:block">
          <Sidebar />
        </div>

        <div className="flex min-h-screen flex-1 flex-col">
          <header className="sticky top-0 z-30 border-b border-border bg-background/90 px-4 py-3 backdrop-blur lg:px-6">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Button variant="outline" size="icon" className="lg:hidden" onClick={() => setMobileMenuOpen(true)}>
                  <Menu className="h-5 w-5" />
                </Button>
                <div>
                  <p className="text-sm font-medium text-foreground">{location.pathname}</p>
                  <p className="text-xs text-muted-foreground">{tokenSummary}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2">
                <div className="text-right">
                  <p className="text-sm font-semibold leading-none">{user?.username}</p>
                  <p className="mt-1 text-xs uppercase tracking-wide text-muted-foreground">{user?.role}</p>
                  {user?.tenant_id ? <p className="mt-1 font-mono text-[10px] text-muted-foreground">{user.tenant_id}</p> : null}
                </div>
                <Button variant="ghost" size="icon" onClick={onLogout}>
                  <LogOut className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </header>

          <main className="flex-1 px-4 py-6 lg:px-6">
            <Outlet />
          </main>
        </div>
      </div>

      {mobileMenuOpen ? (
        <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setMobileMenuOpen(false)}>
          <div className="h-full w-72" onClick={(event) => event.stopPropagation()}>
            <Sidebar onClose={() => setMobileMenuOpen(false)} />
          </div>
        </div>
      ) : null}
    </div>
  )
}
