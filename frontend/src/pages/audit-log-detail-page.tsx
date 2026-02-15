import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { getAuditLog } from '@/features/audit-logs/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import { EmptyState } from '@/shared/ui/empty-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Spinner } from '@/shared/ui/spinner'

export function AuditLogDetailPage() {
  const { logId = '' } = useParams<{ logId: string }>()

  const logQuery = useQuery({
    queryKey: ['audit-log', logId],
    queryFn: () => getAuditLog(logId),
    enabled: Boolean(logId),
  })

  return (
    <>
      <PageHeader
        title="감사 로그 상세"
        description="단일 감사 레코드의 메타데이터를 조회합니다."
        actions={
          <Button asChild variant="outline">
            <Link to="/audit-logs">목록으로</Link>
          </Button>
        }
      />

      {logQuery.isLoading ? (
        <div className="flex h-24 items-center justify-center">
          <Spinner />
        </div>
      ) : logQuery.isError ? (
        <EmptyState title="감사 로그 상세 조회 실패" description={resolveErrorMessage(logQuery.error)} />
      ) : logQuery.data ? (
        <div className="grid gap-4 lg:grid-cols-[1fr,1fr]">
          <Card>
            <CardHeader>
              <CardTitle>{logQuery.data.action}</CardTitle>
              <CardDescription>ID: {logQuery.data.id}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p>
                <strong>actor_user_id:</strong> {logQuery.data.actor_user_id || '-'}
              </p>
              <p>
                <strong>actor_username:</strong> {logQuery.data.actor_username || '-'}
              </p>
              <p>
                <strong>target_type:</strong> {logQuery.data.target_type}
              </p>
              <p>
                <strong>target_id:</strong> {logQuery.data.target_id || '-'}
              </p>
              <p>
                <strong>request_id:</strong> {logQuery.data.request_id || '-'}
              </p>
              <p>
                <strong>ip_address:</strong> {logQuery.data.ip_address || '-'}
              </p>
              <p>
                <strong>user_agent:</strong> {logQuery.data.user_agent || '-'}
              </p>
              <p>
                <strong>created_at:</strong> {formatDateTime(logQuery.data.created_at)}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>metadata</CardTitle>
              <CardDescription>원본 JSON</CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="max-h-[560px] overflow-auto rounded-lg bg-muted p-3 text-xs">
                {JSON.stringify(logQuery.data.metadata, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </div>
      ) : (
        <EmptyState title="감사 로그를 찾을 수 없습니다." />
      )}
    </>
  )
}
