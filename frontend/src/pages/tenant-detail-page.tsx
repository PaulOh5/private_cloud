import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCcw, Settings2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { listAuditLogs } from '@/features/audit-logs/api'
import { listInstances } from '@/features/instances/api'
import { listTasks } from '@/features/tasks/api'
import { getTenant, getTenantUsage, updateTenant, updateTenantQuota } from '@/features/tenants/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { instanceStatusLabel, statusTone, taskStatusLabel } from '@/shared/lib/status'
import { cn } from '@/shared/lib/utils'
import type { AuditLog, InstanceStatus, TaskStatus } from '@/types/api'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/ui/dialog'
import { EmptyState } from '@/shared/ui/empty-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { PageHeader } from '@/shared/ui/page-header'
import { Spinner } from '@/shared/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'

const instanceStatusOrder: InstanceStatus[] = [
  'running',
  'creating_pending',
  'updating_pending',
  'deleting_pending',
  'stopped',
  'error',
  'deleted',
]

const taskStatusOrder: TaskStatus[] = ['queued', 'running', 'cancel_pending', 'succeeded', 'failed', 'canceled']

type TrendBucket = {
  label: string
  count: number
}

const updateTenantSchema = z.object({
  name: z.string().min(1, '이름을 입력하세요.').max(128),
  is_active: z.boolean(),
})

type UpdateTenantForm = z.infer<typeof updateTenantSchema>

const quotaSchema = z.object({
  max_instances: z.number().int().positive('1 이상 입력하세요.'),
  max_cpu: z.number().int().positive('1 이상 입력하세요.'),
  max_memory_mib: z.number().int().positive('1 이상 입력하세요.'),
  max_disk_gib: z.number().int().positive('1 이상 입력하세요.'),
})

type QuotaForm = z.infer<typeof quotaSchema>

function UsageBar({ label, used, max, unit }: { label: string; used: number; max: number; unit: string }) {
  const ratio = max > 0 ? used / max : 0
  const percent = Math.max(0, Math.min(100, Math.round(ratio * 100)))
  const toneClass = ratio >= 0.9 ? 'bg-destructive' : ratio >= 0.7 ? 'bg-amber-500' : 'bg-primary'

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span>{label}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {used} / {max} {unit}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-muted">
        <div className={cn('h-full transition-all', toneClass)} style={{ width: `${percent}%` }} />
      </div>
      <p className="text-right text-xs text-muted-foreground">{percent}%</p>
    </div>
  )
}

function DistributionBar({ label, count, total }: { label: string; count: number; total: number }) {
  const percent = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span>{label}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {count} ({percent}%)
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-muted">
        <div className="h-full bg-primary/80" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

function TrendBars({
  title,
  description,
  buckets,
}: {
  title: string
  description: string
  buckets: TrendBucket[]
}) {
  const max = Math.max(...buckets.map((bucket) => bucket.count), 1)

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {buckets.map((bucket) => {
          const percent = Math.max(0, Math.min(100, Math.round((bucket.count / max) * 100)))
          return (
            <div key={bucket.label} className="flex items-center gap-2 text-xs">
              <span className="w-14 shrink-0 text-muted-foreground">{bucket.label}</span>
              <div className="h-2 flex-1 overflow-hidden rounded bg-muted">
                <div className="h-full bg-primary/85" style={{ width: `${percent}%` }} />
              </div>
              <span className="w-8 shrink-0 text-right font-mono text-muted-foreground">{bucket.count}</span>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function buildDailyBuckets(logs: AuditLog[]): TrendBucket[] {
  const now = new Date()
  const labels: TrendBucket[] = []
  const keys = new Map<string, number>()

  for (let i = 6; i >= 0; i -= 1) {
    const day = new Date(now)
    day.setDate(now.getDate() - i)
    day.setHours(0, 0, 0, 0)
    const key = day.toISOString().slice(0, 10)
    const label = `${String(day.getMonth() + 1).padStart(2, '0')}/${String(day.getDate()).padStart(2, '0')}`
    keys.set(key, labels.length)
    labels.push({ label, count: 0 })
  }

  for (const item of logs) {
    const key = item.created_at.slice(0, 10)
    const index = keys.get(key)
    if (index !== undefined) {
      labels[index].count += 1
    }
  }

  return labels
}

function buildHourlyBuckets(logs: AuditLog[]): TrendBucket[] {
  const now = Date.now()
  const bucketSizeMs = 2 * 60 * 60 * 1000
  const bucketCount = 12
  const start = now - bucketSizeMs * bucketCount

  const buckets = Array.from({ length: bucketCount }, (_, index) => {
    const bucketStart = start + index * bucketSizeMs
    const hour = new Date(bucketStart).getHours()
    return {
      label: `${String(hour).padStart(2, '0')}h`,
      count: 0,
      start: bucketStart,
      end: bucketStart + bucketSizeMs,
    }
  })

  for (const item of logs) {
    const created = new Date(item.created_at).getTime()
    if (Number.isNaN(created) || created < start || created > now) {
      continue
    }
    const index = Math.min(bucketCount - 1, Math.floor((created - start) / bucketSizeMs))
    buckets[index].count += 1
  }

  return buckets.map(({ label, count }) => ({ label, count }))
}

export function TenantDetailPage() {
  const { tenantId = '' } = useParams<{ tenantId: string }>()
  const queryClient = useQueryClient()

  const [updateOpen, setUpdateOpen] = useState(false)
  const [quotaOpen, setQuotaOpen] = useState(false)

  const tenantQuery = useQuery({
    queryKey: ['tenant', tenantId],
    queryFn: () => getTenant(tenantId),
    enabled: Boolean(tenantId),
  })

  const usageQuery = useQuery({
    queryKey: ['tenant-usage', tenantId],
    queryFn: () => getTenantUsage(tenantId),
    enabled: Boolean(tenantId),
    refetchInterval: 15_000,
  })

  const instancesQuery = useQuery({
    queryKey: ['instances', 'tenant-detail', tenantId],
    queryFn: () => listInstances({ limit: 200, offset: 0, tenant_id: tenantId }),
    enabled: Boolean(tenantId),
    refetchInterval: 15_000,
  })

  const tasksQuery = useQuery({
    queryKey: ['tasks', 'tenant-detail', tenantId],
    queryFn: () => listTasks({ limit: 200, offset: 0, tenant_id: tenantId }),
    enabled: Boolean(tenantId),
    refetchInterval: 15_000,
  })

  const logsQuery = useQuery({
    queryKey: ['audit-logs', 'tenant-detail', tenantId],
    queryFn: () => listAuditLogs({ limit: 100, offset: 0, tenant_id: tenantId }),
    enabled: Boolean(tenantId),
    refetchInterval: 30_000,
  })

  const updateForm = useForm<UpdateTenantForm>({
    resolver: zodResolver(updateTenantSchema),
    defaultValues: {
      name: '',
      is_active: true,
    },
  })

  const quotaForm = useForm<QuotaForm>({
    resolver: zodResolver(quotaSchema),
    defaultValues: {
      max_instances: 1,
      max_cpu: 1,
      max_memory_mib: 1,
      max_disk_gib: 1,
    },
  })

  useEffect(() => {
    if (!tenantQuery.data) {
      return
    }
    updateForm.reset({
      name: tenantQuery.data.name,
      is_active: tenantQuery.data.is_active,
    })
    if (tenantQuery.data.quota) {
      quotaForm.reset({
        max_instances: tenantQuery.data.quota.max_instances,
        max_cpu: tenantQuery.data.quota.max_cpu,
        max_memory_mib: tenantQuery.data.quota.max_memory_mib,
        max_disk_gib: tenantQuery.data.quota.max_disk_gib,
      })
    }
  }, [tenantQuery.data, updateForm, quotaForm])

  const updateMutation = useMutation({
    mutationFn: (payload: UpdateTenantForm) => updateTenant(tenantId, payload),
    onSuccess: () => {
      toast.success('Tenant 정보가 수정되었습니다.')
      setUpdateOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['tenant', tenantId] })
      void queryClient.invalidateQueries({ queryKey: ['tenants'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const quotaMutation = useMutation({
    mutationFn: (payload: QuotaForm) => updateTenantQuota(tenantId, payload),
    onSuccess: () => {
      toast.success('Quota가 수정되었습니다.')
      setQuotaOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['tenant', tenantId] })
      void queryClient.invalidateQueries({ queryKey: ['tenant-usage', tenantId] })
      void queryClient.invalidateQueries({ queryKey: ['tenants'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const instanceDistribution = useMemo(() => {
    const counts = instanceStatusOrder.reduce<Record<InstanceStatus, number>>(
      (acc, status) => {
        acc[status] = 0
        return acc
      },
      {} as Record<InstanceStatus, number>,
    )
    for (const item of instancesQuery.data?.items ?? []) {
      counts[item.status] += 1
    }
    return counts
  }, [instancesQuery.data?.items])

  const taskDistribution = useMemo(() => {
    const counts = taskStatusOrder.reduce<Record<TaskStatus, number>>(
      (acc, status) => {
        acc[status] = 0
        return acc
      },
      {} as Record<TaskStatus, number>,
    )
    for (const item of tasksQuery.data?.items ?? []) {
      counts[item.status] += 1
    }
    return counts
  }, [tasksQuery.data?.items])

  const logs = useMemo(() => logsQuery.data?.items ?? [], [logsQuery.data?.items])

  const activitySummary = useMemo(() => {
    const counters = new Map<string, number>()
    for (const item of logs) {
      const key = item.action.split('.')[0] || item.action
      counters.set(key, (counters.get(key) ?? 0) + 1)
    }
    return [...counters.entries()].sort((a, b) => b[1] - a[1])
  }, [logs])

  const dailyBuckets = useMemo(() => buildDailyBuckets(logs), [logs])
  const hourlyBuckets = useMemo(() => buildHourlyBuckets(logs), [logs])

  const recentInstances = useMemo(
    () => [...(instancesQuery.data?.items ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 8),
    [instancesQuery.data?.items],
  )

  const recentTasks = useMemo(
    () => [...(tasksQuery.data?.items ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 8),
    [tasksQuery.data?.items],
  )

  const isLoading = tenantQuery.isLoading || usageQuery.isLoading || instancesQuery.isLoading || tasksQuery.isLoading
  const isError = tenantQuery.isError || usageQuery.isError || instancesQuery.isError || tasksQuery.isError

  const totalInstances = instancesQuery.data?.items.length ?? 0
  const totalTasks = tasksQuery.data?.items.length ?? 0

  const onRefresh = () => {
    void tenantQuery.refetch()
    void usageQuery.refetch()
    void instancesQuery.refetch()
    void tasksQuery.refetch()
    void logsQuery.refetch()
  }

  return (
    <>
      <PageHeader
        title="Tenant 상세"
        description="사용량/Quota/활동 이력을 종합해서 tenant 상태를 확인합니다."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/tenants">목록으로</Link>
            </Button>
            <Button variant="outline" onClick={onRefresh}>
              <RefreshCcw className="mr-2 h-4 w-4" />
              새로고침
            </Button>
            <Button variant="outline" onClick={() => setUpdateOpen(true)} disabled={!tenantQuery.data}>
              <Settings2 className="mr-2 h-4 w-4" />
              Tenant 수정
            </Button>
            <Button onClick={() => setQuotaOpen(true)} disabled={!tenantQuery.data?.quota}>
              Quota 수정
            </Button>
          </>
        }
      />

      {isLoading ? (
        <div className="flex h-24 items-center justify-center">
          <Spinner />
        </div>
      ) : isError ? (
        <EmptyState
          title="Tenant 상세 조회 실패"
          description={resolveErrorMessage(tenantQuery.error ?? usageQuery.error ?? instancesQuery.error ?? tasksQuery.error)}
        />
      ) : tenantQuery.data && usageQuery.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>{tenantQuery.data.name}</CardTitle>
                <CardDescription>
                  key: <span className="font-mono">{tenantQuery.data.key}</span>
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  <strong>ID:</strong> <span className="font-mono text-xs">{tenantQuery.data.id}</span>
                </p>
                <p>
                  <strong>상태:</strong>{' '}
                  <Badge tone={tenantQuery.data.is_active ? 'success' : 'neutral'}>
                    {tenantQuery.data.is_active ? 'active' : 'inactive'}
                  </Badge>
                </p>
                <p>
                  <strong>생성 시각:</strong> {formatDateTime(tenantQuery.data.created_at)}
                </p>
                <p>
                  <strong>수정 시각:</strong> {formatDateTime(tenantQuery.data.updated_at)}
                </p>
              </CardContent>
            </Card>

            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>Quota 대비 사용량</CardTitle>
                <CardDescription>예약 자원 기준 사용률과 잔여량을 동시에 확인합니다.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {tenantQuery.data.quota ? (
                  <>
                    <div className="grid gap-3 text-sm md:grid-cols-4">
                      <div className="rounded-md border border-border bg-muted/50 p-3">
                        <p className="text-xs text-muted-foreground">Instances 잔여</p>
                        <p className="mt-1 font-mono text-base">
                          {tenantQuery.data.quota.max_instances - usageQuery.data.used_instances}
                        </p>
                      </div>
                      <div className="rounded-md border border-border bg-muted/50 p-3">
                        <p className="text-xs text-muted-foreground">CPU 잔여</p>
                        <p className="mt-1 font-mono text-base">{tenantQuery.data.quota.max_cpu - usageQuery.data.used_cpu}</p>
                      </div>
                      <div className="rounded-md border border-border bg-muted/50 p-3">
                        <p className="text-xs text-muted-foreground">Memory 잔여</p>
                        <p className="mt-1 font-mono text-base">
                          {tenantQuery.data.quota.max_memory_mib - usageQuery.data.used_memory_mib} MiB
                        </p>
                      </div>
                      <div className="rounded-md border border-border bg-muted/50 p-3">
                        <p className="text-xs text-muted-foreground">Disk 잔여</p>
                        <p className="mt-1 font-mono text-base">
                          {tenantQuery.data.quota.max_disk_gib - usageQuery.data.used_disk_gib} GiB
                        </p>
                      </div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <UsageBar
                        label="Instances"
                        used={usageQuery.data.used_instances}
                        max={tenantQuery.data.quota.max_instances}
                        unit="ea"
                      />
                      <UsageBar label="CPU" used={usageQuery.data.used_cpu} max={tenantQuery.data.quota.max_cpu} unit="vCPU" />
                      <UsageBar
                        label="Memory"
                        used={usageQuery.data.used_memory_mib}
                        max={tenantQuery.data.quota.max_memory_mib}
                        unit="MiB"
                      />
                      <UsageBar
                        label="Disk"
                        used={usageQuery.data.used_disk_gib}
                        max={tenantQuery.data.quota.max_disk_gib}
                        unit="GiB"
                      />
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Quota 정보가 없습니다.</p>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>인스턴스 상태 분포</CardTitle>
                <CardDescription>총 {totalInstances}개 인스턴스</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {instanceStatusOrder.map((status) => (
                  <DistributionBar
                    key={status}
                    label={instanceStatusLabel[status]}
                    count={instanceDistribution[status]}
                    total={totalInstances}
                  />
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>작업 상태 분포</CardTitle>
                <CardDescription>총 {totalTasks}개 작업 (최근 최대 200건)</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {taskStatusOrder.map((status) => (
                  <DistributionBar
                    key={status}
                    label={taskStatusLabel[status]}
                    count={taskDistribution[status]}
                    total={totalTasks}
                  />
                ))}
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <TrendBars
              title="활동 이력 (최근 7일)"
              description="감사 로그 발생 건수 일별 집계"
              buckets={dailyBuckets}
            />
            <TrendBars
              title="활동 이력 (최근 24시간)"
              description="2시간 버킷 단위 감사 로그 집계"
              buckets={hourlyBuckets}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>활동 요약</CardTitle>
                <CardDescription>action prefix 기준</CardDescription>
              </CardHeader>
              <CardContent>
                {activitySummary.length ? (
                  <div className="space-y-2 text-sm">
                    {activitySummary.slice(0, 8).map(([key, count]) => (
                      <div key={key} className="flex items-center justify-between rounded bg-muted px-3 py-2">
                        <span>{key}</span>
                        <span className="font-mono text-xs">{count}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="활동 이력이 없습니다." />
                )}
              </CardContent>
            </Card>

            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>최근 감사 로그</CardTitle>
                <CardDescription>tenant 기준 최근 20건</CardDescription>
              </CardHeader>
              <CardContent>
                {logsQuery.isLoading ? (
                  <div className="flex h-20 items-center justify-center">
                    <Spinner />
                  </div>
                ) : logsQuery.isError ? (
                  <EmptyState title="감사 로그 조회 실패" description={resolveErrorMessage(logsQuery.error)} />
                ) : logs.length ? (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>시각</TableHead>
                          <TableHead>action</TableHead>
                          <TableHead>actor</TableHead>
                          <TableHead>target</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {logs.slice(0, 20).map((log) => (
                          <TableRow key={log.id}>
                            <TableCell>{formatDateTime(log.created_at)}</TableCell>
                            <TableCell>{log.action}</TableCell>
                            <TableCell>{log.actor_username || '-'}</TableCell>
                            <TableCell>
                              {log.target_type} / {log.target_id || '-'}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <EmptyState title="감사 로그가 없습니다." />
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>최근 인스턴스 변경</CardTitle>
                <CardDescription>수정 시각 기준 상위 8건</CardDescription>
              </CardHeader>
              <CardContent>
                {recentInstances.length ? (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>인스턴스</TableHead>
                          <TableHead>상태</TableHead>
                          <TableHead>스펙</TableHead>
                          <TableHead>수정 시각</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {recentInstances.map((instance) => (
                          <TableRow key={instance.id}>
                            <TableCell>
                              <Link className="font-medium hover:underline" to={`/instances/${instance.id}`}>
                                {instance.name || '(이름 없음)'}
                              </Link>
                              <p className="font-mono text-xs text-muted-foreground">{instance.id}</p>
                            </TableCell>
                            <TableCell>
                              <Badge tone={statusTone[instance.status]}>{instanceStatusLabel[instance.status]}</Badge>
                            </TableCell>
                            <TableCell className="text-xs">
                              {instance.cpu} vCPU / {instance.memory_mib} MiB / {instance.disk_gib} GiB
                            </TableCell>
                            <TableCell>{formatDateTime(instance.updated_at)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <EmptyState title="표시할 인스턴스 이력이 없습니다." />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>최근 작업 이력</CardTitle>
                <CardDescription>생성 시각 기준 상위 8건</CardDescription>
              </CardHeader>
              <CardContent>
                {recentTasks.length ? (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Task ID</TableHead>
                          <TableHead>명령</TableHead>
                          <TableHead>상태</TableHead>
                          <TableHead>생성 시각</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {recentTasks.map((task) => (
                          <TableRow key={task.id}>
                            <TableCell>
                              <Link className="font-mono text-xs hover:underline" to={`/tasks/${task.id}`}>
                                {task.id}
                              </Link>
                            </TableCell>
                            <TableCell>{task.command}</TableCell>
                            <TableCell>
                              <Badge tone={statusTone[task.status]}>{taskStatusLabel[task.status]}</Badge>
                            </TableCell>
                            <TableCell>{formatDateTime(task.created_at)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <EmptyState title="표시할 작업 이력이 없습니다." />
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <EmptyState title="Tenant를 찾을 수 없습니다." />
      )}

      <Dialog open={updateOpen} onOpenChange={setUpdateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tenant 수정</DialogTitle>
            <DialogDescription>ID: {tenantQuery.data?.id}</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={updateForm.handleSubmit((value) => updateMutation.mutate(value))}>
            <div>
              <Label htmlFor="tenant-name">name</Label>
              <Input id="tenant-name" {...updateForm.register('name')} />
              {updateForm.formState.errors.name?.message ? (
                <p className="mt-1 text-xs text-destructive">{updateForm.formState.errors.name.message}</p>
              ) : null}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...updateForm.register('is_active')} />
              활성 상태
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setUpdateOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? '저장 중...' : '저장'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={quotaOpen} onOpenChange={setQuotaOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Quota 수정</DialogTitle>
            <DialogDescription>현재 사용량보다 낮게 설정하면 서버에서 거부됩니다.</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={quotaForm.handleSubmit((value) => quotaMutation.mutate(value))}>
            <div className="rounded-md bg-muted p-3 text-sm">
              현재 사용량: {usageQuery.data?.used_instances ?? 0} inst / {usageQuery.data?.used_cpu ?? 0} cpu /{' '}
              {usageQuery.data?.used_memory_mib ?? 0} MiB / {usageQuery.data?.used_disk_gib ?? 0} GiB
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <Label htmlFor="quota-max-instances">max_instances</Label>
                <Input id="quota-max-instances" type="number" {...quotaForm.register('max_instances', { valueAsNumber: true })} />
              </div>
              <div>
                <Label htmlFor="quota-max-cpu">max_cpu</Label>
                <Input id="quota-max-cpu" type="number" {...quotaForm.register('max_cpu', { valueAsNumber: true })} />
              </div>
              <div>
                <Label htmlFor="quota-max-memory">max_memory_mib</Label>
                <Input id="quota-max-memory" type="number" {...quotaForm.register('max_memory_mib', { valueAsNumber: true })} />
              </div>
              <div>
                <Label htmlFor="quota-max-disk">max_disk_gib</Label>
                <Input id="quota-max-disk" type="number" {...quotaForm.register('max_disk_gib', { valueAsNumber: true })} />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setQuotaOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={quotaMutation.isPending}>
                {quotaMutation.isPending ? '저장 중...' : '저장'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
