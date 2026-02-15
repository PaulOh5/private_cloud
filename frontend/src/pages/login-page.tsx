import { zodResolver } from '@hookform/resolvers/zod'
import { LockKeyhole } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { useAuth } from '@/features/auth/auth-context'
import { resolveErrorMessage } from '@/shared/lib/error'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'

const loginSchema = z.object({
  username: z.string().min(3, '아이디는 최소 3자 이상이어야 합니다.'),
  password: z.string().min(1, '비밀번호를 입력해주세요.'),
})

type LoginFormValue = z.infer<typeof loginSchema>

export function LoginPage() {
  const { isAuthenticated, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const form = useForm<LoginFormValue>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      username: '',
      password: '',
    },
  })

  if (isAuthenticated) {
    return <Navigate to="/instances" replace />
  }

  const onSubmit = form.handleSubmit(async (value) => {
    setErrorMessage(null)
    try {
      await login(value.username, value.password)
      const next = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? '/instances'
      navigate(next, { replace: true })
    } catch (error) {
      if (error instanceof Error) {
        setErrorMessage(error.message)
      } else {
        setErrorMessage(resolveErrorMessage(error))
      }
    }
  })

  return (
    <div className="min-h-screen bg-background">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(circle_at_10%_20%,hsl(var(--primary)/0.22),transparent_35%),radial-gradient(circle_at_85%_15%,hsl(24_88%_59%/0.2),transparent_35%),linear-gradient(180deg,hsl(220_25%_97%),hsl(220_25%_94%))]" />
      <div className="mx-auto flex min-h-screen w-full max-w-6xl items-center justify-center px-4 py-12">
        <Card className="w-full max-w-md border-none bg-card/90 shadow-2xl backdrop-blur-sm">
          <CardHeader>
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/90 text-primary-foreground">
              <LockKeyhole className="h-5 w-5" />
            </div>
            <CardTitle>운영 콘솔 로그인</CardTitle>
            <CardDescription>기본 계정: admin / admin1234</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={onSubmit}>
              <div>
                <Label htmlFor="username">아이디</Label>
                <Input id="username" autoComplete="username" {...form.register('username')} />
                {form.formState.errors.username?.message ? (
                  <p className="mt-1 text-xs text-destructive">{form.formState.errors.username.message}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="password">비밀번호</Label>
                <Input id="password" type="password" autoComplete="current-password" {...form.register('password')} />
                {form.formState.errors.password?.message ? (
                  <p className="mt-1 text-xs text-destructive">{form.formState.errors.password.message}</p>
                ) : null}
              </div>
              {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}
              <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
                {form.formState.isSubmitting ? '로그인 중...' : '로그인'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
