import { useQuery } from '@tanstack/react-query'
import { Eye, RefreshCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { listAuditLogs } from '@/features/audit-logs/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { toOffset } from '@/shared/lib/pagination'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import { EmptyState } from '@/shared/ui/empty-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { PageHeader } from '@/shared/ui/page-header'
import { Pagination } from '@/shared/ui/pagination'
import { Spinner } from '@/shared/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'

const pageSize = 20

export function AuditLogsPage() {
  const [page, setPage] = useState(1)
  const [actorUserIdFilter, setActorUserIdFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [targetTypeFilter, setTargetTypeFilter] = useState('')
  const [requestIdFilter, setRequestIdFilter] = useState('')

  const params = useMemo(
    () => ({
      limit: pageSize,
      offset: toOffset(page, pageSize),
      actor_user_id: actorUserIdFilter || undefined,
      action: actionFilter || undefined,
      target_type: targetTypeFilter || undefined,
      request_id: requestIdFilter || undefined,
    }),
    [page, actorUserIdFilter, actionFilter, targetTypeFilter, requestIdFilter],
  )

  const logsQuery = useQuery({
    queryKey: ['audit-logs', params],
    queryFn: () => listAuditLogs(params),
    placeholderData: (previous) => previous,
  })

  return (
    <>
      <PageHeader
        title="감사 로그"
        description="사용자 인증 및 운영 액션 이력을 조회합니다."
        actions={
          <Button variant="outline" onClick={() => void logsQuery.refetch()}>
            <RefreshCcw className="mr-2 h-4 w-4" />
            새로고침
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>필터</CardTitle>
          <CardDescription>actor_user_id / action / target_type / request_id 조건 지원</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
            <div>
              <Label htmlFor="actor-user-id">actor_user_id</Label>
              <Input
                id="actor-user-id"
                value={actorUserIdFilter}
                onChange={(event) => setActorUserIdFilter(event.target.value)}
                placeholder="UUID"
              />
            </div>
            <div>
              <Label htmlFor="action-filter">action</Label>
              <Input
                id="action-filter"
                value={actionFilter}
                onChange={(event) => setActionFilter(event.target.value)}
                placeholder="예: user.create"
              />
            </div>
            <div>
              <Label htmlFor="target-type">target_type</Label>
              <Input
                id="target-type"
                value={targetTypeFilter}
                onChange={(event) => setTargetTypeFilter(event.target.value)}
                placeholder="예: user"
              />
            </div>
            <div>
              <Label htmlFor="request-id">request_id</Label>
              <Input
                id="request-id"
                value={requestIdFilter}
                onChange={(event) => setRequestIdFilter(event.target.value)}
                placeholder="UUID"
              />
            </div>
            <div className="flex items-end">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => {
                  setPage(1)
                  void logsQuery.refetch()
                }}
              >
                조회 적용
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>로그 목록</CardTitle>
          <CardDescription>최근 생성순으로 표시됩니다.</CardDescription>
        </CardHeader>
        <CardContent>
          {logsQuery.isLoading ? (
            <div className="flex h-24 items-center justify-center">
              <Spinner />
            </div>
          ) : logsQuery.isError ? (
            <EmptyState title="감사 로그 조회 실패" description={resolveErrorMessage(logsQuery.error)} />
          ) : logsQuery.data?.items.length ? (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>action</TableHead>
                      <TableHead>target</TableHead>
                      <TableHead>actor</TableHead>
                      <TableHead>created_at</TableHead>
                      <TableHead className="text-right">상세</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {logsQuery.data.items.map((log) => (
                      <TableRow key={log.id}>
                        <TableCell className="font-mono text-xs">{log.id}</TableCell>
                        <TableCell>{log.action}</TableCell>
                        <TableCell>
                          {log.target_type} / {log.target_id || '-'}
                        </TableCell>
                        <TableCell>{log.actor_username || '-'}</TableCell>
                        <TableCell>{formatDateTime(log.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <Button asChild size="sm" variant="outline">
                              <Link to={`/audit-logs/${log.id}`}>
                                <Eye className="mr-1 h-4 w-4" /> 상세
                              </Link>
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <Pagination
                total={logsQuery.data.total}
                limit={pageSize}
                page={page}
                onPageChange={(nextPage) => setPage(nextPage)}
              />
            </>
          ) : (
            <EmptyState title="감사 로그가 없습니다." />
          )}
        </CardContent>
      </Card>
    </>
  )
}
