import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { getTask } from '@/features/tasks/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { statusTone, taskStatusLabel } from '@/shared/lib/status'
import type { TaskStatus } from '@/types/api'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import { EmptyState } from '@/shared/ui/empty-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Spinner } from '@/shared/ui/spinner'

export function TaskDetailPage() {
  const { taskId = '' } = useParams<{ taskId: string }>()

  const taskQuery = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => getTask(taskId),
    enabled: Boolean(taskId),
    refetchInterval: (query) => {
      const task = query.state.data
      if (!task) {
        return false
      }
      return task.status === 'queued' || task.status === 'running' || task.status === 'cancel_pending' ? 5000 : false
    },
  })

  return (
    <>
      <PageHeader
        title="작업 상세"
        description="비동기 작업의 요청/결과 payload와 실행 이력을 확인합니다."
        actions={
          <Button asChild variant="outline">
            <Link to="/tasks">목록으로</Link>
          </Button>
        }
      />

      {taskQuery.isLoading ? (
        <div className="flex h-24 items-center justify-center">
          <Spinner />
        </div>
      ) : taskQuery.isError ? (
        <EmptyState title="작업 상세 조회 실패" description={resolveErrorMessage(taskQuery.error)} />
      ) : taskQuery.data ? (
        <div className="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
          <Card>
            <CardHeader>
              <CardTitle>기본 정보</CardTitle>
              <CardDescription>ID: {taskQuery.data.id}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p>
                <strong>인스턴스:</strong>{' '}
                <Link className="font-mono text-primary hover:underline" to={`/instances/${taskQuery.data.instance_id}`}>
                  {taskQuery.data.instance_id}
                </Link>
              </p>
              <p>
                <strong>명령:</strong> {taskQuery.data.command}
              </p>
              <p>
                <strong>상태:</strong>{' '}
                <Badge tone={statusTone[taskQuery.data.status]}>
                  {taskStatusLabel[taskQuery.data.status as TaskStatus]}
                </Badge>
              </p>
              <p>
                <strong>시도 횟수:</strong> {taskQuery.data.attempt_count}/{taskQuery.data.max_attempts}
              </p>
              <p>
                <strong>에러 코드:</strong> {taskQuery.data.error_code || '-'}
              </p>
              <p>
                <strong>에러 메시지:</strong> {taskQuery.data.error_message || '-'}
              </p>
              <p>
                <strong>생성 시각:</strong> {formatDateTime(taskQuery.data.created_at)}
              </p>
              <p>
                <strong>시작 시각:</strong> {formatDateTime(taskQuery.data.started_at)}
              </p>
              <p>
                <strong>종료 시각:</strong> {formatDateTime(taskQuery.data.finished_at)}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Payload</CardTitle>
              <CardDescription>요청/결과 JSON</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <p className="mb-1 text-sm font-medium">request_payload</p>
                <pre className="max-h-56 overflow-auto rounded-lg bg-muted p-3 text-xs">
                  {JSON.stringify(taskQuery.data.request_payload, null, 2)}
                </pre>
              </div>
              <div>
                <p className="mb-1 text-sm font-medium">result_payload</p>
                <pre className="max-h-56 overflow-auto rounded-lg bg-muted p-3 text-xs">
                  {JSON.stringify(taskQuery.data.result_payload, null, 2)}
                </pre>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : (
        <EmptyState title="작업을 찾을 수 없습니다." />
      )}
    </>
  )
}
