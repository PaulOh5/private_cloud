import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, useParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/auth-context'
import { getUser } from '@/features/users/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import { EmptyState } from '@/shared/ui/empty-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Spinner } from '@/shared/ui/spinner'

export function UserDetailPage() {
  const { userId = '' } = useParams<{ userId: string }>()
  const { user } = useAuth()

  const canView = Boolean(user && (user.role === 'admin' || user.id === userId))

  const userQuery = useQuery({
    queryKey: ['user', userId],
    queryFn: () => getUser(userId),
    enabled: Boolean(userId && canView),
  })

  if (!canView) {
    return <Navigate to="/unauthorized" replace />
  }

  return (
    <>
      <PageHeader
        title="사용자 상세"
        description="단일 사용자 정보를 조회합니다."
        actions={
          user?.role === 'admin' ? (
            <Button asChild variant="outline">
              <Link to="/users">목록으로</Link>
            </Button>
          ) : null
        }
      />

      {userQuery.isLoading ? (
        <div className="flex h-24 items-center justify-center">
          <Spinner />
        </div>
      ) : userQuery.isError ? (
        <EmptyState title="사용자 상세 조회 실패" description={resolveErrorMessage(userQuery.error)} />
      ) : userQuery.data ? (
        <Card>
          <CardHeader>
            <CardTitle>{userQuery.data.username}</CardTitle>
            <CardDescription>ID: {userQuery.data.id}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm md:grid-cols-2">
            <p>
              <strong>역할:</strong> {userQuery.data.role}
            </p>
            <p>
              <strong>tenant_id:</strong> <span className="font-mono">{userQuery.data.tenant_id || '-'}</span>
            </p>
            <p>
              <strong>활성 상태:</strong>{' '}
              <Badge tone={userQuery.data.is_active ? 'success' : 'neutral'}>
                {userQuery.data.is_active ? 'active' : 'inactive'}
              </Badge>
            </p>
            <p>
              <strong>생성 시각:</strong> {formatDateTime(userQuery.data.created_at)}
            </p>
            <p>
              <strong>수정 시각:</strong> {formatDateTime(userQuery.data.updated_at)}
            </p>
          </CardContent>
        </Card>
      ) : (
        <EmptyState title="사용자를 찾을 수 없습니다." />
      )}
    </>
  )
}
