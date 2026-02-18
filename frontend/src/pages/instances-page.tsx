import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, PauseCircle, PlayCircle, Plus, RefreshCcw, Settings2, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { useAuth } from '@/features/auth/auth-context'
import {
  createInstance,
  deleteInstance,
  listInstances,
  listVmImages,
  startInstance,
  stopInstance,
  updateInstance,
  type CreateInstancePayload,
  type UpdateInstancePayload,
} from '@/features/instances/api'
import { listTenants } from '@/features/tenants/api'
import { resolveErrorMessage } from '@/shared/lib/error'
import { toOffset } from '@/shared/lib/pagination'
import { instanceStatusLabel, statusTone } from '@/shared/lib/status'
import type { Instance, Tenant } from '@/types/api'
import { formatDateTime } from '@/shared/lib/date'
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
import { Pagination } from '@/shared/ui/pagination'
import { Select } from '@/shared/ui/select'
import { Spinner } from '@/shared/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'

const instanceFormSchema = z.object({
  tenant_id: z
    .string()
    .refine((value) => value === '' || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value), {
      message: '유효한 tenant_id를 입력하세요.',
    }),
  name: z.string().max(128, '이름은 128자를 넘길 수 없습니다.').optional(),
  cpu: z.number().int().positive('CPU는 1 이상이어야 합니다.'),
  memory_mib: z.number().int().positive('메모리는 1 이상이어야 합니다.'),
  disk_gib: z.number().int().positive('디스크는 1 이상이어야 합니다.'),
  image_id: z.string().max(64, '이미지 ID는 64자를 넘길 수 없습니다.').optional(),
})

type InstanceFormValues = z.infer<typeof instanceFormSchema>

const updateFormSchema = instanceFormSchema.pick({
  cpu: true,
  memory_mib: true,
  disk_gib: true,
})
type UpdateFormValues = z.infer<typeof updateFormSchema>

const pageSize = 20

const statusOptions = [
  { value: '', label: '전체 상태' },
  { value: 'creating_pending', label: 'creating_pending' },
  { value: 'updating_pending', label: 'updating_pending' },
  { value: 'starting_pending', label: 'starting_pending' },
  { value: 'stopping_pending', label: 'stopping_pending' },
  { value: 'deleting_pending', label: 'deleting_pending' },
  { value: 'running', label: 'running' },
  { value: 'stopped', label: 'stopped' },
  { value: 'error', label: 'error' },
  { value: 'deleted', label: 'deleted' },
]

export function InstancesPage() {
  const queryClient = useQueryClient()
  const { hasAnyRole } = useAuth()
  const canManage = hasAnyRole('admin', 'operator')
  const isAdmin = hasAnyRole('admin')

  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [nameFilter, setNameFilter] = useState('')
  const [tenantFilter, setTenantFilter] = useState('')
  const [includeDeleted, setIncludeDeleted] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [updateTarget, setUpdateTarget] = useState<Instance | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Instance | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState('')

  const params = useMemo(
    () => ({
      limit: pageSize,
      offset: toOffset(page, pageSize),
      status: statusFilter || undefined,
      name: nameFilter || undefined,
      tenant_id: isAdmin ? tenantFilter || undefined : undefined,
    }),
    [page, statusFilter, nameFilter, isAdmin, tenantFilter],
  )

  const instancesQuery = useQuery({
    queryKey: ['instances', params],
    queryFn: () => listInstances(params),
    placeholderData: (previous) => previous,
    refetchInterval: (query) => {
      const payload = query.state.data
      if (!payload) {
        return false
      }

      return payload.items.some((item) => item.status.endsWith('_pending')) ? 5000 : false
    },
  })

  const tenantsQuery = useQuery({
    queryKey: ['tenants', 'instance-page-selector'],
    queryFn: () => listTenants({ limit: 200, offset: 0 }),
    enabled: isAdmin,
    staleTime: 60_000,
  })

  const tenantOptions = useMemo<Tenant[]>(() => tenantsQuery.data?.items ?? [], [tenantsQuery.data?.items])

  const visibleItems = useMemo(() => {
    const items = instancesQuery.data?.items ?? []
    if (includeDeleted) {
      return items
    }
    return items.filter((item) => item.status !== 'deleted')
  }, [instancesQuery.data?.items, includeDeleted])

  const vmImagesQuery = useQuery({
    queryKey: ['vm-images'],
    queryFn: listVmImages,
    staleTime: 60_000,
  })

  const defaultImageId = useMemo(
    () => vmImagesQuery.data?.find((item) => item.is_default)?.id ?? '',
    [vmImagesQuery.data],
  )

  const createForm = useForm<InstanceFormValues>({
    resolver: zodResolver(instanceFormSchema),
    defaultValues: {
      tenant_id: '',
      name: '',
      cpu: 2,
      memory_mib: 2048,
      disk_gib: 20,
      image_id: '',
    },
  })

  const updateForm = useForm<UpdateFormValues>({
    resolver: zodResolver(updateFormSchema),
    defaultValues: {
      cpu: 1,
      memory_mib: 1024,
      disk_gib: 20,
    },
  })

  useEffect(() => {
    if (!updateTarget) {
      return
    }

    updateForm.reset({
      cpu: updateTarget.cpu,
      memory_mib: updateTarget.memory_mib,
      disk_gib: updateTarget.disk_gib,
    })
  }, [updateTarget, updateForm])

  useEffect(() => {
    if (!createOpen) {
      return
    }
    const currentImage = createForm.getValues('image_id')
    if (!currentImage && defaultImageId) {
      createForm.setValue('image_id', defaultImageId, { shouldValidate: true })
    }
    if (isAdmin) {
      const currentTenant = createForm.getValues('tenant_id')
      if (!currentTenant) {
        const fallbackTenant = tenantFilter || tenantOptions[0]?.id || ''
        if (fallbackTenant) {
          createForm.setValue('tenant_id', fallbackTenant, { shouldValidate: true })
        }
      }
    }
  }, [createOpen, defaultImageId, createForm, isAdmin, tenantFilter, tenantOptions])

  const createMutation = useMutation({
    mutationFn: (payload: CreateInstancePayload) => createInstance(payload),
    onSuccess: (result) => {
      toast.success(`생성 요청이 등록되었습니다. task_id=${result.task_id}`)
      setCreateOpen(false)
      createForm.reset({
        tenant_id: isAdmin ? tenantFilter || tenantOptions[0]?.id || '' : '',
        name: '',
        cpu: 2,
        memory_mib: 2048,
        disk_gib: 20,
        image_id: defaultImageId,
      })
      void queryClient.invalidateQueries({ queryKey: ['instances'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => {
      toast.error(resolveErrorMessage(error))
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateInstancePayload }) => updateInstance(id, payload),
    onSuccess: (result) => {
      toast.success(`수정 요청이 등록되었습니다. task_id=${result.task_id}`)
      setUpdateTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['instances'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => {
      toast.error(resolveErrorMessage(error))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteInstance(id),
    onSuccess: (result) => {
      toast.success(`삭제 요청이 등록되었습니다. task_id=${result.task_id}`)
      setDeleteTarget(null)
      setDeleteConfirm('')
      void queryClient.invalidateQueries({ queryKey: ['instances'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => {
      toast.error(resolveErrorMessage(error))
    },
  })

  const startMutation = useMutation({
    mutationFn: (id: string) => startInstance(id),
    onSuccess: (result) => {
      toast.success(`시작 요청이 등록되었습니다. task_id=${result.task_id}`)
      void queryClient.invalidateQueries({ queryKey: ['instances'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => {
      toast.error(resolveErrorMessage(error))
    },
  })

  const stopMutation = useMutation({
    mutationFn: (id: string) => stopInstance(id),
    onSuccess: (result) => {
      toast.success(`중지 요청이 등록되었습니다. task_id=${result.task_id}`)
      void queryClient.invalidateQueries({ queryKey: ['instances'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => {
      toast.error(resolveErrorMessage(error))
    },
  })

  const onCreate = createForm.handleSubmit((value) => {
    if (isAdmin && !value.tenant_id) {
      toast.error('admin은 tenant_id를 선택해야 합니다.')
      return
    }
    createMutation.mutate({
      tenant_id: isAdmin ? value.tenant_id || undefined : undefined,
      name: value.name || undefined,
      cpu: value.cpu,
      memory_mib: value.memory_mib,
      disk_gib: value.disk_gib,
      image_id: value.image_id || undefined,
    })
  })

  const onUpdate = updateForm.handleSubmit((value) => {
    if (!updateTarget) {
      return
    }

    updateMutation.mutate({
      id: updateTarget.id,
      payload: value,
    })
  })

  const onDelete = () => {
    if (!deleteTarget) {
      return
    }

    if (deleteConfirm !== deleteTarget.id) {
      toast.error('인스턴스 ID가 일치하지 않습니다.')
      return
    }

    deleteMutation.mutate(deleteTarget.id)
  }

  return (
    <>
      <PageHeader
        title="인스턴스"
        description="VM 인스턴스를 조회하고 생성/수정/삭제 요청을 비동기 작업으로 발행합니다."
        actions={
          <>
            <Button variant="outline" onClick={() => void instancesQuery.refetch()}>
              <RefreshCcw className="mr-2 h-4 w-4" />
              새로고침
            </Button>
            {canManage ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                인스턴스 생성
              </Button>
            ) : null}
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>필터</CardTitle>
          <CardDescription>status/name 조건으로 목록을 조회합니다.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
            <div>
              <Label htmlFor="status-filter">상태</Label>
              <Select id="status-filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="name-filter">이름</Label>
              <Input
                id="name-filter"
                placeholder="예: web-node"
                value={nameFilter}
                onChange={(event) => setNameFilter(event.target.value)}
              />
            </div>
            {isAdmin ? (
              <div>
                <Label htmlFor="tenant-filter">Tenant</Label>
                <Select id="tenant-filter" value={tenantFilter} onChange={(event) => setTenantFilter(event.target.value)}>
                  <option value="">전체 Tenant</option>
                  {tenantOptions.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name} ({tenant.key})
                    </option>
                  ))}
                </Select>
              </div>
            ) : null}
            <div className="flex items-end">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => {
                  setPage(1)
                  void instancesQuery.refetch()
                }}
              >
                조회 적용
              </Button>
            </div>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={includeDeleted}
                onChange={(event) => setIncludeDeleted(event.target.checked)}
              />
              삭제 상태 포함
            </label>
          </div>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>인스턴스 목록</CardTitle>
          <CardDescription>기본 페이지 크기: 20</CardDescription>
        </CardHeader>
        <CardContent>
          {instancesQuery.isLoading ? (
            <div className="flex h-24 items-center justify-center">
              <Spinner />
            </div>
          ) : instancesQuery.isError ? (
            <EmptyState title="목록 조회 실패" description={resolveErrorMessage(instancesQuery.error)} />
          ) : visibleItems.length === 0 ? (
            <EmptyState title="표시할 인스턴스가 없습니다." description="필터 조건을 변경하거나 새로 생성해보세요." />
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      {isAdmin ? <TableHead>Tenant</TableHead> : null}
                      <TableHead>이름</TableHead>
                      <TableHead>스펙</TableHead>
                      <TableHead>상태</TableHead>
                      <TableHead>IP</TableHead>
                      <TableHead>생성 시각</TableHead>
                      <TableHead className="text-right">액션</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visibleItems.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="font-mono text-xs">{item.id}</TableCell>
                        {isAdmin ? <TableCell className="font-mono text-xs">{item.tenant_id}</TableCell> : null}
                        <TableCell>{item.name || '-'}</TableCell>
                        <TableCell>{item.cpu} vCPU / {item.memory_mib} MiB / {item.disk_gib} GiB</TableCell>
                        <TableCell>
                          <Badge tone={statusTone[item.status]}>{instanceStatusLabel[item.status]}</Badge>
                        </TableCell>
                        <TableCell>{item.ip_address || '-'}</TableCell>
                        <TableCell>{formatDateTime(item.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-2">
                            <Button asChild size="sm" variant="outline">
                              <Link to={`/instances/${item.id}`}>
                                <Eye className="mr-1 h-4 w-4" /> 상세
                              </Link>
                            </Button>
                            {canManage ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => {
                                    if (item.status === 'running') {
                                      stopMutation.mutate(item.id)
                                    } else {
                                      startMutation.mutate(item.id)
                                    }
                                  }}
                                  disabled={
                                    item.status.endsWith('_pending') ||
                                    item.status === 'deleted' ||
                                    (item.status !== 'running' && item.status !== 'stopped') ||
                                    startMutation.isPending ||
                                    stopMutation.isPending
                                  }
                                >
                                  {item.status === 'running' ? (
                                    <>
                                      <PauseCircle className="mr-1 h-4 w-4" /> 중지
                                    </>
                                  ) : (
                                    <>
                                      <PlayCircle className="mr-1 h-4 w-4" /> 시작
                                    </>
                                  )}
                                </Button>
                                <Button size="sm" variant="outline" onClick={() => setUpdateTarget(item)}>
                                  <Settings2 className="mr-1 h-4 w-4" /> 수정
                                </Button>
                                <Button size="sm" variant="destructive" onClick={() => setDeleteTarget(item)}>
                                  <Trash2 className="mr-1 h-4 w-4" /> 삭제
                                </Button>
                              </>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <Pagination
                total={instancesQuery.data?.total ?? 0}
                limit={pageSize}
                page={page}
                onPageChange={(nextPage) => {
                  setPage(nextPage)
                }}
              />
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>인스턴스 생성</DialogTitle>
            <DialogDescription>요청이 수락되면 비동기 작업(task)이 큐에 등록됩니다.</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={onCreate}>
            {isAdmin ? (
              <div>
                <Label htmlFor="create-tenant">Tenant</Label>
                <Select id="create-tenant" {...createForm.register('tenant_id')}>
                  <option value="">Tenant 선택</option>
                  {tenantOptions.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name} ({tenant.key})
                    </option>
                  ))}
                </Select>
                {createForm.formState.errors.tenant_id?.message ? (
                  <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.tenant_id.message}</p>
                ) : null}
              </div>
            ) : null}
            <div>
              <Label htmlFor="create-name">이름</Label>
              <Input id="create-name" placeholder="선택 입력" {...createForm.register('name')} />
              {createForm.formState.errors.name?.message ? (
                <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.name.message}</p>
              ) : null}
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div>
                <Label htmlFor="create-cpu">CPU</Label>
                <Input id="create-cpu" type="number" {...createForm.register('cpu', { valueAsNumber: true })} />
                {createForm.formState.errors.cpu?.message ? (
                  <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.cpu.message}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="create-mem">메모리(MiB)</Label>
                <Input
                  id="create-mem"
                  type="number"
                  {...createForm.register('memory_mib', { valueAsNumber: true })}
                />
                {createForm.formState.errors.memory_mib?.message ? (
                  <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.memory_mib.message}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="create-disk">디스크(GiB)</Label>
                <Input
                  id="create-disk"
                  type="number"
                  {...createForm.register('disk_gib', { valueAsNumber: true })}
                />
                {createForm.formState.errors.disk_gib?.message ? (
                  <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.disk_gib.message}</p>
                ) : null}
              </div>
            </div>
            <div>
              <Label htmlFor="create-image">베이스 이미지</Label>
              <Select id="create-image" {...createForm.register('image_id')}>
                <option value="">기본 이미지 자동 선택</option>
                {(vmImagesQuery.data ?? []).map((image) => (
                  <option key={image.id} value={image.id}>
                    {image.id}
                    {image.is_default ? ' (default)' : ''}
                  </option>
                ))}
              </Select>
              {vmImagesQuery.isLoading ? (
                <p className="mt-1 text-xs text-muted-foreground">이미지 카탈로그를 불러오는 중입니다.</p>
              ) : null}
              {vmImagesQuery.isError ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  이미지 목록 조회에 실패했습니다. 비워두면 서버 기본 이미지로 생성됩니다.
                </p>
              ) : null}
              {createForm.formState.errors.image_id?.message ? (
                <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.image_id.message}</p>
              ) : null}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? '요청 중...' : '생성 요청'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(updateTarget)} onOpenChange={(open) => !open && setUpdateTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>인스턴스 스펙 수정</DialogTitle>
            <DialogDescription>ID: {updateTarget?.id}</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={onUpdate}>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div>
                <Label htmlFor="update-cpu">CPU</Label>
                <Input id="update-cpu" type="number" {...updateForm.register('cpu', { valueAsNumber: true })} />
                {updateForm.formState.errors.cpu?.message ? (
                  <p className="mt-1 text-xs text-destructive">{updateForm.formState.errors.cpu.message}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="update-mem">메모리(MiB)</Label>
                <Input
                  id="update-mem"
                  type="number"
                  {...updateForm.register('memory_mib', { valueAsNumber: true })}
                />
                {updateForm.formState.errors.memory_mib?.message ? (
                  <p className="mt-1 text-xs text-destructive">{updateForm.formState.errors.memory_mib.message}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="update-disk">디스크(GiB)</Label>
                <Input
                  id="update-disk"
                  type="number"
                  {...updateForm.register('disk_gib', { valueAsNumber: true })}
                />
                {updateForm.formState.errors.disk_gib?.message ? (
                  <p className="mt-1 text-xs text-destructive">{updateForm.formState.errors.disk_gib.message}</p>
                ) : null}
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setUpdateTarget(null)}>
                취소
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? '요청 중...' : '수정 요청'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>인스턴스 삭제 요청</DialogTitle>
            <DialogDescription>
              이 작업은 비동기 삭제 task를 발행합니다. 아래에 대상 인스턴스 ID를 정확히 입력하세요.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md bg-muted p-3 text-sm">
              대상 ID: <span className="font-mono">{deleteTarget?.id}</span>
            </div>
            <div>
              <Label htmlFor="delete-confirm">확인 입력</Label>
              <Input
                id="delete-confirm"
                value={deleteConfirm}
                onChange={(event) => setDeleteConfirm(event.target.value)}
                placeholder="대상 ID를 그대로 입력"
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>
                취소
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={deleteMutation.isPending}
                onClick={onDelete}
              >
                {deleteMutation.isPending ? '요청 중...' : '삭제 요청'}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
