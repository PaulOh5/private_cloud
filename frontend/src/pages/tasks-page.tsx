import { useQuery } from '@tanstack/react-query'
import { Eye, RefreshCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { listTasks } from '@/features/tasks/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { toOffset } from '@/shared/lib/pagination'
import { statusTone, taskStatusLabel } from '@/shared/lib/status'
import type { TaskStatus } from '@/types/api'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import { EmptyState } from '@/shared/ui/empty-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { PageHeader } from '@/shared/ui/page-header'
import { Pagination } from '@/shared/ui/pagination'
import { Select } from '@/shared/ui/select'
import { Spinner } from '@/shared/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'

const pageSize = 20

export function TasksPage() {
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [instanceIdFilter, setInstanceIdFilter] = useState('')
  const [commandFilter, setCommandFilter] = useState('')

  const params = useMemo(
    () => ({
      limit: pageSize,
      offset: toOffset(page, pageSize),
      status: statusFilter || undefined,
      instance_id: instanceIdFilter || undefined,
      command: commandFilter || undefined,
    }),
    [page, statusFilter, instanceIdFilter, commandFilter],
  )

  const tasksQuery = useQuery({
    queryKey: ['tasks', params],
    queryFn: () => listTasks(params),
    placeholderData: (previous) => previous,
    refetchInterval: (query) => {
      const payload = query.state.data
      if (!payload) {
        return false
      }

      return payload.items.some((item) => item.status === 'queued' || item.status === 'running') ? 5000 : false
    },
  })

  return (
    <>
      <PageHeader
        title="작업 이력"
        description="비동기 VM 작업 상태를 조회합니다. queued/running 항목이 있으면 5초 주기로 자동 새로고침됩니다."
        actions={
          <Button variant="outline" onClick={() => void tasksQuery.refetch()}>
            <RefreshCcw className="mr-2 h-4 w-4" />
            새로고침
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>필터</CardTitle>
          <CardDescription>status, instance_id, command 로 검색할 수 있습니다.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <div>
              <Label htmlFor="task-status">상태</Label>
              <Select id="task-status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">전체</option>
                <option value="queued">queued</option>
                <option value="running">running</option>
                <option value="succeeded">succeeded</option>
                <option value="failed">failed</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="task-instance">인스턴스 ID</Label>
              <Input
                id="task-instance"
                value={instanceIdFilter}
                onChange={(event) => setInstanceIdFilter(event.target.value)}
                placeholder="UUID"
              />
            </div>
            <div>
              <Label htmlFor="task-command">명령</Label>
              <Select id="task-command" value={commandFilter} onChange={(event) => setCommandFilter(event.target.value)}>
                <option value="">전체</option>
                <option value="create">create</option>
                <option value="update">update</option>
                <option value="delete">delete</option>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => {
                  setPage(1)
                  void tasksQuery.refetch()
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
          <CardTitle>작업 목록</CardTitle>
          <CardDescription>최근 생성순으로 정렬됩니다.</CardDescription>
        </CardHeader>
        <CardContent>
          {tasksQuery.isLoading ? (
            <div className="flex h-24 items-center justify-center">
              <Spinner />
            </div>
          ) : tasksQuery.isError ? (
            <EmptyState title="작업 조회 실패" description={resolveErrorMessage(tasksQuery.error)} />
          ) : tasksQuery.data?.items.length ? (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>인스턴스</TableHead>
                      <TableHead>명령</TableHead>
                      <TableHead>상태</TableHead>
                      <TableHead>시도</TableHead>
                      <TableHead>생성 시각</TableHead>
                      <TableHead className="text-right">액션</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tasksQuery.data.items.map((task) => (
                      <TableRow key={task.id}>
                        <TableCell className="font-mono text-xs">{task.id}</TableCell>
                        <TableCell>
                          <Link to={`/instances/${task.instance_id}`} className="font-mono text-xs text-primary hover:underline">
                            {task.instance_id}
                          </Link>
                        </TableCell>
                        <TableCell>{task.command}</TableCell>
                        <TableCell>
                          <Badge tone={statusTone[task.status]}>{taskStatusLabel[task.status as TaskStatus]}</Badge>
                        </TableCell>
                        <TableCell>
                          {task.attempt_count}/{task.max_attempts}
                        </TableCell>
                        <TableCell>{formatDateTime(task.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <Button asChild size="sm" variant="outline">
                              <Link to={`/tasks/${task.id}`}>
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
                total={tasksQuery.data.total}
                limit={pageSize}
                page={page}
                onPageChange={(nextPage) => setPage(nextPage)}
              />
            </>
          ) : (
            <EmptyState title="작업이 없습니다." description="인스턴스 생성/수정/삭제 요청 이후 작업이 생성됩니다." />
          )}
        </CardContent>
      </Card>
    </>
  )
}
