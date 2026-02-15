import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, Pencil, Plus, RefreshCcw, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  createTenant,
  deleteTenant,
  getTenantUsage,
  listTenants,
  type CreateTenantPayload,
  type UpdateTenantPayload,
  type UpdateTenantQuotaPayload,
  updateTenant,
  updateTenantQuota,
} from '@/features/tenants/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { toOffset } from '@/shared/lib/pagination'
import type { Tenant } from '@/types/api'
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

const pageSize = 20

const createTenantSchema = z.object({
  key: z
    .string()
    .min(2, 'key는 최소 2자입니다.')
    .max(64, 'key는 최대 64자입니다.')
    .regex(/^[a-z0-9][a-z0-9._-]{1,63}$/, 'key 형식이 올바르지 않습니다.'),
  name: z.string().min(1, '이름을 입력하세요.').max(128),
  is_active: z.boolean(),
  max_instances: z.number().int().positive('1 이상 입력하세요.'),
  max_cpu: z.number().int().positive('1 이상 입력하세요.'),
  max_memory_mib: z.number().int().positive('1 이상 입력하세요.'),
  max_disk_gib: z.number().int().positive('1 이상 입력하세요.'),
})

type CreateTenantForm = z.infer<typeof createTenantSchema>

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

export function TenantsPage() {
  const queryClient = useQueryClient()

  const [page, setPage] = useState(1)
  const [activeFilter, setActiveFilter] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [updateTarget, setUpdateTarget] = useState<Tenant | null>(null)
  const [quotaTarget, setQuotaTarget] = useState<Tenant | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Tenant | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState('')

  const params = useMemo(
    () => ({
      limit: pageSize,
      offset: toOffset(page, pageSize),
      is_active: activeFilter ? activeFilter === 'true' : undefined,
    }),
    [page, activeFilter],
  )

  const tenantsQuery = useQuery({
    queryKey: ['tenants', params],
    queryFn: () => listTenants(params),
    placeholderData: (previous) => previous,
  })

  const usageQuery = useQuery({
    queryKey: ['tenant-usage', quotaTarget?.id],
    queryFn: () => getTenantUsage(quotaTarget?.id ?? ''),
    enabled: Boolean(quotaTarget?.id),
  })

  const createForm = useForm<CreateTenantForm>({
    resolver: zodResolver(createTenantSchema),
    defaultValues: {
      key: '',
      name: '',
      is_active: true,
      max_instances: 100,
      max_cpu: 16,
      max_memory_mib: 32768,
      max_disk_gib: 500,
    },
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
      max_instances: 100,
      max_cpu: 16,
      max_memory_mib: 32768,
      max_disk_gib: 500,
    },
  })

  useEffect(() => {
    if (!updateTarget) {
      return
    }
    updateForm.reset({
      name: updateTarget.name,
      is_active: updateTarget.is_active,
    })
  }, [updateTarget, updateForm])

  useEffect(() => {
    if (!quotaTarget?.quota) {
      return
    }
    quotaForm.reset({
      max_instances: quotaTarget.quota.max_instances,
      max_cpu: quotaTarget.quota.max_cpu,
      max_memory_mib: quotaTarget.quota.max_memory_mib,
      max_disk_gib: quotaTarget.quota.max_disk_gib,
    })
  }, [quotaTarget, quotaForm])

  const createMutation = useMutation({
    mutationFn: (payload: CreateTenantPayload) => createTenant(payload),
    onSuccess: (created) => {
      toast.success(`Tenant 생성 완료: ${created.name}`)
      setCreateOpen(false)
      createForm.reset({
        key: '',
        name: '',
        is_active: true,
        max_instances: 100,
        max_cpu: 16,
        max_memory_mib: 32768,
        max_disk_gib: 500,
      })
      void queryClient.invalidateQueries({ queryKey: ['tenants'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateTenantPayload }) => updateTenant(id, payload),
    onSuccess: (updated) => {
      toast.success(`Tenant 수정 완료: ${updated.name}`)
      setUpdateTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['tenants'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const quotaMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateTenantQuotaPayload }) => updateTenantQuota(id, payload),
    onSuccess: () => {
      toast.success('Quota 수정 완료')
      setQuotaTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['tenants'] })
      void queryClient.invalidateQueries({ queryKey: ['tenant-usage'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteTenant(id),
    onSuccess: () => {
      toast.success('Tenant가 삭제되었습니다.')
      setDeleteTarget(null)
      setDeleteConfirm('')
      void queryClient.invalidateQueries({ queryKey: ['tenants'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const onCreate = createForm.handleSubmit((value) => {
    createMutation.mutate(value)
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

  const onUpdateQuota = quotaForm.handleSubmit((value) => {
    if (!quotaTarget) {
      return
    }
    quotaMutation.mutate({
      id: quotaTarget.id,
      payload: value,
    })
  })

  const onDelete = () => {
    if (!deleteTarget) {
      return
    }
    if (deleteConfirm !== deleteTarget.id) {
      toast.error('Tenant ID 확인 입력이 일치하지 않습니다.')
      return
    }
    deleteMutation.mutate(deleteTarget.id)
  }

  return (
    <>
      <PageHeader
        title="Tenant 관리"
        description="테넌트 활성 상태와 리소스 Quota를 관리합니다."
        actions={
          <>
            <Button variant="outline" onClick={() => void tenantsQuery.refetch()}>
              <RefreshCcw className="mr-2 h-4 w-4" />
              새로고침
            </Button>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Tenant 생성
            </Button>
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>필터</CardTitle>
          <CardDescription>활성 상태 조건으로 tenant를 조회합니다.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <Label htmlFor="tenant-active-filter">활성 여부</Label>
              <Select id="tenant-active-filter" value={activeFilter} onChange={(event) => setActiveFilter(event.target.value)}>
                <option value="">전체</option>
                <option value="true">active</option>
                <option value="false">inactive</option>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => {
                  setPage(1)
                  void tenantsQuery.refetch()
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
          <CardTitle>Tenant 목록</CardTitle>
          <CardDescription>최근 생성순으로 정렬됩니다.</CardDescription>
        </CardHeader>
        <CardContent>
          {tenantsQuery.isLoading ? (
            <div className="flex h-24 items-center justify-center">
              <Spinner />
            </div>
          ) : tenantsQuery.isError ? (
            <EmptyState title="Tenant 조회 실패" description={resolveErrorMessage(tenantsQuery.error)} />
          ) : tenantsQuery.data?.items.length ? (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>key</TableHead>
                      <TableHead>name</TableHead>
                      <TableHead>활성</TableHead>
                      <TableHead>quota</TableHead>
                      <TableHead>생성 시각</TableHead>
                      <TableHead className="text-right">액션</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tenantsQuery.data.items.map((tenant) => (
                      <TableRow key={tenant.id}>
                        <TableCell className="font-mono text-xs">{tenant.id}</TableCell>
                        <TableCell>{tenant.key}</TableCell>
                        <TableCell>{tenant.name}</TableCell>
                        <TableCell>
                          <Badge tone={tenant.is_active ? 'success' : 'neutral'}>
                            {tenant.is_active ? 'active' : 'inactive'}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs">
                          {tenant.quota
                            ? `${tenant.quota.max_instances} inst / ${tenant.quota.max_cpu} cpu / ${tenant.quota.max_memory_mib} MiB / ${tenant.quota.max_disk_gib} GiB`
                            : '-'}
                        </TableCell>
                        <TableCell>{formatDateTime(tenant.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-2">
                            <Button asChild size="sm" variant="outline">
                              <Link to={`/tenants/${tenant.id}`}>
                                <Eye className="mr-1 h-4 w-4" /> 상세
                              </Link>
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => setQuotaTarget(tenant)}>
                              Quota
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => setUpdateTarget(tenant)}>
                              <Pencil className="mr-1 h-4 w-4" /> 수정
                            </Button>
                            <Button size="sm" variant="destructive" onClick={() => setDeleteTarget(tenant)}>
                              <Trash2 className="mr-1 h-4 w-4" /> 삭제
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <Pagination
                total={tenantsQuery.data.total}
                limit={pageSize}
                page={page}
                onPageChange={(nextPage) => setPage(nextPage)}
              />
            </>
          ) : (
            <EmptyState title="Tenant 데이터가 없습니다." />
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tenant 생성</DialogTitle>
            <DialogDescription>새 tenant와 초기 quota를 함께 생성합니다.</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={onCreate}>
            <div>
              <Label htmlFor="tenant-key">key</Label>
              <Input id="tenant-key" {...createForm.register('key')} placeholder="예: team-a" />
              {createForm.formState.errors.key?.message ? (
                <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.key.message}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="tenant-name">name</Label>
              <Input id="tenant-name" {...createForm.register('name')} placeholder="예: Team A" />
              {createForm.formState.errors.name?.message ? (
                <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.name.message}</p>
              ) : null}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...createForm.register('is_active')} />
              생성 즉시 활성화
            </label>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <Label htmlFor="create-max-instances">max_instances</Label>
                <Input id="create-max-instances" type="number" {...createForm.register('max_instances', { valueAsNumber: true })} />
              </div>
              <div>
                <Label htmlFor="create-max-cpu">max_cpu</Label>
                <Input id="create-max-cpu" type="number" {...createForm.register('max_cpu', { valueAsNumber: true })} />
              </div>
              <div>
                <Label htmlFor="create-max-memory">max_memory_mib</Label>
                <Input id="create-max-memory" type="number" {...createForm.register('max_memory_mib', { valueAsNumber: true })} />
              </div>
              <div>
                <Label htmlFor="create-max-disk">max_disk_gib</Label>
                <Input id="create-max-disk" type="number" {...createForm.register('max_disk_gib', { valueAsNumber: true })} />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? '생성 중...' : '생성'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(updateTarget)} onOpenChange={(open) => !open && setUpdateTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tenant 수정</DialogTitle>
            <DialogDescription>ID: {updateTarget?.id}</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={onUpdate}>
            <div>
              <Label htmlFor="update-tenant-name">name</Label>
              <Input id="update-tenant-name" {...updateForm.register('name')} />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...updateForm.register('is_active')} />
              활성 상태
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setUpdateTarget(null)}>
                취소
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? '저장 중...' : '저장'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(quotaTarget)} onOpenChange={(open) => !open && setQuotaTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tenant Quota/Usage</DialogTitle>
            <DialogDescription>ID: {quotaTarget?.id}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {usageQuery.isLoading ? (
              <div className="flex h-16 items-center justify-center">
                <Spinner />
              </div>
            ) : usageQuery.data ? (
              <div className="rounded-md bg-muted p-3 text-sm">
                usage: {usageQuery.data.used_instances} inst / {usageQuery.data.used_cpu} cpu / {usageQuery.data.used_memory_mib} MiB /{' '}
                {usageQuery.data.used_disk_gib} GiB
              </div>
            ) : null}

            <form className="space-y-3" onSubmit={onUpdateQuota}>
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
                <Button type="button" variant="outline" onClick={() => setQuotaTarget(null)}>
                  취소
                </Button>
                <Button type="submit" disabled={quotaMutation.isPending}>
                  {quotaMutation.isPending ? '저장 중...' : 'Quota 저장'}
                </Button>
              </DialogFooter>
            </form>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tenant 삭제</DialogTitle>
            <DialogDescription>
              안전 확인을 위해 대상 tenant ID를 입력하세요. active user/instance가 있으면 삭제가 거부됩니다.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md bg-muted p-3 text-sm">
              대상: <strong>{deleteTarget?.name}</strong> / <span className="font-mono">{deleteTarget?.id}</span>
            </div>
            <div>
              <Label htmlFor="delete-tenant-confirm">확인 입력</Label>
              <Input
                id="delete-tenant-confirm"
                value={deleteConfirm}
                onChange={(event) => setDeleteConfirm(event.target.value)}
                placeholder="대상 ID를 그대로 입력"
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>
                취소
              </Button>
              <Button type="button" variant="destructive" disabled={deleteMutation.isPending} onClick={onDelete}>
                {deleteMutation.isPending ? '삭제 중...' : '삭제'}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
