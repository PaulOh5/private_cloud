import RFB from '@novnc/novnc/lib/rfb'
import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { useAuth } from '@/features/auth/auth-context'
import { getInstance, issueConsoleTicket } from '@/features/instances/api'
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

type ConsoleConnectionState = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'

const consoleStateLabel: Record<ConsoleConnectionState, string> = {
  idle: '대기',
  connecting: '연결 중',
  connected: '연결됨',
  disconnected: '연결 종료',
  error: '오류',
}

function buildConsoleWebsocketUrl(websocketPath: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api${websocketPath}`
}

export function InstanceDetailPage() {
  const { instanceId = '' } = useParams<{ instanceId: string }>()
  const { hasAnyRole } = useAuth()
  const canUseConsole = hasAnyRole('admin', 'operator')

  const [consoleState, setConsoleState] = useState<ConsoleConnectionState>('idle')
  const [consoleMessage, setConsoleMessage] = useState('연결 버튼을 눌러 웹 콘솔을 시작하세요.')
  const consoleHostRef = useRef<HTMLDivElement | null>(null)
  const rfbRef = useRef<RFB | null>(null)

  const closeConsoleSession = useCallback(() => {
    if (rfbRef.current) {
      rfbRef.current.disconnect()
      rfbRef.current = null
    }
  }, [])

  useEffect(() => {
    return () => {
      closeConsoleSession()
    }
  }, [closeConsoleSession])

  useEffect(() => {
    closeConsoleSession()
  }, [instanceId, closeConsoleSession])

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

  const consoleUnavailableReason = useMemo(() => {
    if (!canUseConsole) {
      return '콘솔 접속 권한이 없습니다. (admin/operator 전용)'
    }
    if (!instanceQuery.data) {
      return '인스턴스 정보를 불러오는 중입니다.'
    }
    if (instanceQuery.data.status !== 'running') {
      return `현재 상태가 ${instanceStatusLabel[instanceQuery.data.status]}이므로 콘솔 접속이 비활성화됩니다.`
    }
    return null
  }, [canUseConsole, instanceQuery.data])

  const canDisconnectConsole = consoleState === 'connected' || consoleState === 'connecting'

  const onConnectConsole = async () => {
    if (!instanceId || !canUseConsole || !instanceQuery.data || instanceQuery.data.status !== 'running') {
      return
    }
    const host = consoleHostRef.current
    if (!host) {
      setConsoleState('error')
      setConsoleMessage('콘솔 렌더링 영역을 찾을 수 없습니다.')
      return
    }

    setConsoleState('connecting')
    setConsoleMessage('콘솔 티켓 발급 및 연결을 준비하고 있습니다.')

    try {
      closeConsoleSession()
      host.replaceChildren()

      const ticket = await issueConsoleTicket(instanceId)
      const url = buildConsoleWebsocketUrl(ticket.websocket_path)

      const rfb = new RFB(host, url, { wsProtocols: ['binary'] })
      rfb.scaleViewport = true
      // QEMU VNC generally does not support noVNC SetDesktopSize negotiation reliably.
      // Keep client-side scaling only to avoid resize negotiation failures.
      rfb.resizeSession = false
      rfbRef.current = rfb

      rfb.addEventListener('connect', () => {
        setConsoleState('connected')
        setConsoleMessage('웹 콘솔에 연결되었습니다.')
      })
      rfb.addEventListener('disconnect', (event: Event & { detail?: { clean?: boolean } }) => {
        rfbRef.current = null
        if (event.detail?.clean) {
          setConsoleState('disconnected')
          setConsoleMessage('콘솔 연결이 정상 종료되었습니다.')
        } else {
          setConsoleState('error')
          setConsoleMessage('콘솔 연결이 비정상 종료되었습니다.')
        }
      })
      rfb.addEventListener('credentialsrequired', () => {
        setConsoleState('error')
        setConsoleMessage('예상치 못한 VNC 자격 증명 요청이 발생했습니다.')
        closeConsoleSession()
      })
    } catch (error) {
      setConsoleState('error')
      const message = resolveErrorMessage(error)
      setConsoleMessage(message)
      toast.error(message)
      closeConsoleSession()
    }
  }

  const onDisconnectConsole = () => {
    closeConsoleSession()
    setConsoleState('disconnected')
    setConsoleMessage('사용자 요청으로 콘솔 연결을 종료했습니다.')
  }

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
                <strong>tenant_id:</strong> <span className="font-mono">{instanceQuery.data.tenant_id}</span>
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
              <CardTitle>웹 콘솔 (noVNC)</CardTitle>
              <CardDescription>SSH 연결 없이 브라우저에서 VM 콘솔을 직접 확인합니다.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  onClick={() => {
                    void onConnectConsole()
                  }}
                  disabled={Boolean(consoleUnavailableReason) || consoleState === 'connecting'}
                >
                  {consoleState === 'connecting' ? '연결 중...' : '콘솔 연결'}
                </Button>
                <Button variant="outline" onClick={onDisconnectConsole} disabled={!canDisconnectConsole}>
                  연결 종료
                </Button>
                <Badge tone={consoleState === 'error' ? 'danger' : consoleState === 'connected' ? 'success' : 'neutral'}>
                  {consoleStateLabel[consoleState]}
                </Badge>
              </div>

              {consoleUnavailableReason ? <p className="text-sm text-muted-foreground">{consoleUnavailableReason}</p> : null}
              <p className="text-sm text-muted-foreground">{consoleMessage}</p>

              <div className="overflow-hidden rounded-lg border border-border bg-black">
                <div ref={consoleHostRef} className="h-[420px] w-full" />
              </div>
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
