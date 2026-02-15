import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { getInstance } from '@/features/instances/api'
import { listTasks } from '@/features/tasks/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { instanceStatusLabel, statusTone, taskStatusLabel } from '@/shared/lib/status'
import type { TaskStatus } from '@/types/api'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import { EmptyState } from '@/shared/ui/empty-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Spinner } from '@/shared/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'

export function InstanceDetailPage() {
  const { instanceId = '' } = useParams<{ instanceId: string }>()

  const instanceQuery = useQuery({
    queryKey: ['instance', instanceId],
    queryFn: () => getInstance(instanceId),
    enabled: Boolean(instanceId),
    refetchInterval: (query) => {
      const instance = query.state.data
      if (!instance) {
        return false
      }
      return instance.status.endsWith('_pending') ? 5000 : false
    },
  })

  const relatedTasksQuery = useQuery({
    queryKey: ['tasks', 'instance', instanceId],
    queryFn: () =>
      listTasks({
        limit: 20,
        offset: 0,
        instance_id: instanceId,
      }),
    enabled: Boolean(instanceId),
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
        title="인스턴스 상세"
        description="단일 인스턴스 상태와 관련 작업 이력을 확인합니다."
        actions={
          <Button asChild variant="outline">
            <Link to="/instances">목록으로</Link>
          </Button>
        }
      />

      {instanceQuery.isLoading ? (
        <div className="flex h-24 items-center justify-center">
          <Spinner />
        </div>
      ) : instanceQuery.isError ? (
        <EmptyState title="인스턴스 조회 실패" description={resolveErrorMessage(instanceQuery.error)} />
      ) : instanceQuery.data ? (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>{instanceQuery.data.name || '(이름 없음)'}</CardTitle>
              <CardDescription>ID: {instanceQuery.data.id}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm md:grid-cols-2">
              <p>
                <strong>상태:</strong>{' '}
                <Badge tone={statusTone[instanceQuery.data.status]}>{instanceStatusLabel[instanceQuery.data.status]}</Badge>
              </p>
              <p>
                <strong>호스트:</strong> {instanceQuery.data.host_node}
              </p>
              <p>
                <strong>IP:</strong> {instanceQuery.data.ip_address || '-'}
              </p>
              <p>
                <strong>스펙:</strong> {instanceQuery.data.cpu} vCPU / {instanceQuery.data.memory_mib} MiB / {instanceQuery.data.disk_gib} GiB
              </p>
              <p>
                <strong>생성 시각:</strong> {formatDateTime(instanceQuery.data.created_at)}
              </p>
              <p>
                <strong>수정 시각:</strong> {formatDateTime(instanceQuery.data.updated_at)}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>관련 작업 (최신 20건)</CardTitle>
              <CardDescription>queued/running 작업이 있으면 자동으로 새로고침됩니다.</CardDescription>
            </CardHeader>
            <CardContent>
              {relatedTasksQuery.isLoading ? (
                <div className="flex h-24 items-center justify-center">
                  <Spinner />
                </div>
              ) : relatedTasksQuery.isError ? (
                <EmptyState title="작업 조회 실패" description={resolveErrorMessage(relatedTasksQuery.error)} />
              ) : relatedTasksQuery.data?.items.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Task ID</TableHead>
                        <TableHead>명령</TableHead>
                        <TableHead>상태</TableHead>
                        <TableHead>생성 시각</TableHead>
                        <TableHead className="text-right">상세</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {relatedTasksQuery.data.items.map((task) => (
                        <TableRow key={task.id}>
                          <TableCell className="font-mono text-xs">{task.id}</TableCell>
                          <TableCell>{task.command}</TableCell>
                          <TableCell>
                            <Badge tone={statusTone[task.status]}>{taskStatusLabel[task.status as TaskStatus]}</Badge>
                          </TableCell>
                          <TableCell>{formatDateTime(task.created_at)}</TableCell>
                          <TableCell>
                            <div className="flex justify-end">
                              <Button asChild variant="outline" size="sm">
                                <Link to={`/tasks/${task.id}`}>열기</Link>
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <EmptyState title="관련 작업이 없습니다." />
              )}
            </CardContent>
          </Card>
        </div>
      ) : (
        <EmptyState title="인스턴스를 찾을 수 없습니다." />
      )}
    </>
  )
}
