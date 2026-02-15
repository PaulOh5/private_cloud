import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, Plus, RefreshCcw, Settings2, UserX } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { useAuth } from '@/features/auth/auth-context'
import { listTenants } from '@/features/tenants/api'
import { createUser, deactivateUser, listRoles, listUsers, updateUser } from '@/features/users/api'
import { formatDateTime } from '@/shared/lib/date'
import { resolveErrorMessage } from '@/shared/lib/error'
import { toOffset } from '@/shared/lib/pagination'
import type { Role, User } from '@/types/api'
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

const createUserSchema = z.object({
  username: z.string().min(3, '아이디는 최소 3자 이상이어야 합니다.').max(64),
  password: z.string().min(8, '비밀번호는 최소 8자 이상이어야 합니다.').max(256),
  role: z.enum(['admin', 'operator', 'viewer']),
  tenant_id: z.string().uuid('유효한 tenant_id를 선택하세요.').optional().or(z.literal('')),
  is_active: z.boolean(),
})

type CreateUserForm = z.infer<typeof createUserSchema>

const updateUserSchema = z.object({
  role: z.enum(['admin', 'operator', 'viewer']),
  tenant_id: z.string().uuid('유효한 tenant_id를 선택하세요.').optional().or(z.literal('')),
  is_active: z.boolean(),
  password: z
    .string()
    .max(256)
    .refine((value) => value.length === 0 || value.length >= 8, '비밀번호를 변경하려면 8자 이상 입력하세요.'),
})

type UpdateUserForm = z.infer<typeof updateUserSchema>

export function UsersPage() {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const isAdmin = currentUser?.role === 'admin'

  const [page, setPage] = useState(1)
  const [roleFilter, setRoleFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [usernameFilter, setUsernameFilter] = useState('')
  const [tenantFilter, setTenantFilter] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [updateTarget, setUpdateTarget] = useState<User | null>(null)
  const [deactivateTarget, setDeactivateTarget] = useState<User | null>(null)
  const [deactivateConfirm, setDeactivateConfirm] = useState('')

  const roleQuery = useQuery({
    queryKey: ['roles'],
    queryFn: listRoles,
  })

  const tenantsQuery = useQuery({
    queryKey: ['tenants', 'user-page-selector'],
    queryFn: () => listTenants({ limit: 200, offset: 0 }),
    enabled: isAdmin,
    staleTime: 60_000,
  })

  const params = useMemo(
    () => ({
      limit: pageSize,
      offset: toOffset(page, pageSize),
      role: roleFilter || undefined,
      is_active: activeFilter ? activeFilter === 'true' : undefined,
      username: usernameFilter || undefined,
      tenant_id: tenantFilter || undefined,
    }),
    [page, roleFilter, activeFilter, usernameFilter, tenantFilter],
  )

  const usersQuery = useQuery({
    queryKey: ['users', params],
    queryFn: () => listUsers(params),
    placeholderData: (previous) => previous,
  })

  const createForm = useForm<CreateUserForm>({
    resolver: zodResolver(createUserSchema),
    defaultValues: {
      username: '',
      password: '',
      role: 'viewer',
      tenant_id: '',
      is_active: true,
    },
  })

  const updateForm = useForm<UpdateUserForm>({
    resolver: zodResolver(updateUserSchema),
    defaultValues: {
      role: 'viewer',
      tenant_id: '',
      is_active: true,
      password: '',
    },
  })

  const createRole = useWatch({ control: createForm.control, name: 'role' })
  const updateRole = useWatch({ control: updateForm.control, name: 'role' })

  useEffect(() => {
    if (!updateTarget) {
      return
    }

    updateForm.reset({
      role: updateTarget.role,
      tenant_id: updateTarget.tenant_id || '',
      is_active: updateTarget.is_active,
      password: '',
    })
  }, [updateTarget, updateForm])

  useEffect(() => {
    if (createRole === 'admin') {
      createForm.setValue('tenant_id', '')
    }
  }, [createRole, createForm])

  useEffect(() => {
    if (updateRole === 'admin') {
      updateForm.setValue('tenant_id', '')
    }
  }, [updateRole, updateForm])

  const createMutation = useMutation({
    mutationFn: createUser,
    onSuccess: (created) => {
      toast.success(`사용자 생성 완료: ${created.username}`)
      setCreateOpen(false)
      createForm.reset({
        username: '',
        password: '',
        role: 'viewer',
        tenant_id: '',
        is_active: true,
      })
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string
      payload: { role?: Role; tenant_id?: string | null; is_active?: boolean; password?: string }
    }) => updateUser(id, payload),
    onSuccess: (updated) => {
      toast.success(`사용자 정보 수정 완료: ${updated.username}`)
      setUpdateTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      void queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const deactivateMutation = useMutation({
    mutationFn: deactivateUser,
    onSuccess: () => {
      toast.success('사용자가 비활성화되었습니다.')
      setDeactivateTarget(null)
      setDeactivateConfirm('')
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error) => toast.error(resolveErrorMessage(error)),
  })

  const onCreate = createForm.handleSubmit((value) => {
    if (value.role !== 'admin' && !value.tenant_id) {
      toast.error('operator/viewer 계정은 tenant_id가 필요합니다.')
      return
    }
    createMutation.mutate({
      username: value.username,
      password: value.password,
      role: value.role,
      tenant_id: value.role === 'admin' ? undefined : value.tenant_id || undefined,
      is_active: value.is_active,
    })
  })

  const onUpdate = updateForm.handleSubmit((value) => {
    if (!updateTarget) {
      return
    }
    if (value.role !== 'admin' && !value.tenant_id && !updateTarget.tenant_id) {
      toast.error('operator/viewer 계정은 tenant_id가 필요합니다.')
      return
    }

    updateMutation.mutate({
      id: updateTarget.id,
      payload: {
        role: value.role,
        tenant_id: value.role === 'admin' ? undefined : value.tenant_id || updateTarget.tenant_id || undefined,
        is_active: value.is_active,
        password: value.password || undefined,
      },
    })
  })

  const onDeactivate = () => {
    if (!deactivateTarget) {
      return
    }

    if (deactivateConfirm !== deactivateTarget.id) {
      toast.error('사용자 ID 확인 입력이 일치하지 않습니다.')
      return
    }

    deactivateMutation.mutate(deactivateTarget.id)
  }

  return (
    <>
      <PageHeader
        title="사용자 관리"
        description="admin/operator/viewer 계정과 활성 상태를 관리합니다."
        actions={
          <>
            <Button variant="outline" onClick={() => void usersQuery.refetch()}>
              <RefreshCcw className="mr-2 h-4 w-4" />
              새로고침
            </Button>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              사용자 생성
            </Button>
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>필터</CardTitle>
          <CardDescription>role / is_active / username 조건 조회</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
            <div>
              <Label htmlFor="role-filter">역할</Label>
              <Select id="role-filter" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                <option value="">전체</option>
                {(roleQuery.data?.items ?? []).map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="active-filter">활성 여부</Label>
              <Select id="active-filter" value={activeFilter} onChange={(event) => setActiveFilter(event.target.value)}>
                <option value="">전체</option>
                <option value="true">active</option>
                <option value="false">inactive</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="username-filter">아이디</Label>
              <Input
                id="username-filter"
                value={usernameFilter}
                onChange={(event) => setUsernameFilter(event.target.value)}
                placeholder="부분 일치"
              />
            </div>
            <div>
              <Label htmlFor="tenant-filter">Tenant</Label>
              <Select id="tenant-filter" value={tenantFilter} onChange={(event) => setTenantFilter(event.target.value)}>
                <option value="">전체</option>
                {(tenantsQuery.data?.items ?? []).map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name} ({tenant.key})
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => {
                  setPage(1)
                  void usersQuery.refetch()
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
          <CardTitle>사용자 목록</CardTitle>
          <CardDescription>최근 생성순으로 정렬됩니다.</CardDescription>
        </CardHeader>
        <CardContent>
          {usersQuery.isLoading ? (
            <div className="flex h-24 items-center justify-center">
              <Spinner />
            </div>
          ) : usersQuery.isError ? (
            <EmptyState title="사용자 조회 실패" description={resolveErrorMessage(usersQuery.error)} />
          ) : usersQuery.data?.items.length ? (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>아이디</TableHead>
                      <TableHead>역할</TableHead>
                      <TableHead>Tenant</TableHead>
                      <TableHead>활성</TableHead>
                      <TableHead>생성 시각</TableHead>
                      <TableHead className="text-right">액션</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {usersQuery.data.items.map((user) => (
                      <TableRow key={user.id}>
                        <TableCell className="font-mono text-xs">{user.id}</TableCell>
                        <TableCell>{user.username}</TableCell>
                        <TableCell>{user.role}</TableCell>
                        <TableCell className="font-mono text-xs">{user.tenant_id || '-'}</TableCell>
                        <TableCell>
                          <Badge tone={user.is_active ? 'success' : 'neutral'}>
                            {user.is_active ? 'active' : 'inactive'}
                          </Badge>
                        </TableCell>
                        <TableCell>{formatDateTime(user.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-2">
                            <Button asChild size="sm" variant="outline">
                              <Link to={`/users/${user.id}`}>
                                <Eye className="mr-1 h-4 w-4" /> 상세
                              </Link>
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => setUpdateTarget(user)}>
                              <Settings2 className="mr-1 h-4 w-4" /> 수정
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => setDeactivateTarget(user)}
                              disabled={!user.is_active || user.id === currentUser?.id}
                            >
                              <UserX className="mr-1 h-4 w-4" /> 비활성화
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <Pagination
                total={usersQuery.data.total}
                limit={pageSize}
                page={page}
                onPageChange={(nextPage) => setPage(nextPage)}
              />
            </>
          ) : (
            <EmptyState title="사용자 데이터가 없습니다." />
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>사용자 생성</DialogTitle>
            <DialogDescription>새로운 로컬 계정을 생성합니다.</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={onCreate}>
            <div>
              <Label htmlFor="create-username">아이디</Label>
              <Input id="create-username" {...createForm.register('username')} />
              {createForm.formState.errors.username?.message ? (
                <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.username.message}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="create-password">비밀번호</Label>
              <Input id="create-password" type="password" {...createForm.register('password')} />
              {createForm.formState.errors.password?.message ? (
                <p className="mt-1 text-xs text-destructive">{createForm.formState.errors.password.message}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="create-role">역할</Label>
              <Select id="create-role" {...createForm.register('role')}>
                <option value="admin">admin</option>
                <option value="operator">operator</option>
                <option value="viewer">viewer</option>
              </Select>
            </div>
            {createRole !== 'admin' ? (
              <div>
                <Label htmlFor="create-tenant-id">tenant_id</Label>
                <Select id="create-tenant-id" {...createForm.register('tenant_id')}>
                  <option value="">Tenant 선택</option>
                  {(tenantsQuery.data?.items ?? []).map((tenant) => (
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
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...createForm.register('is_active')} />
              즉시 활성화
            </label>
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
            <DialogTitle>사용자 수정</DialogTitle>
            <DialogDescription>ID: {updateTarget?.id}</DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={onUpdate}>
            <div>
              <Label htmlFor="update-role">역할</Label>
              <Select id="update-role" {...updateForm.register('role')}>
                <option value="admin">admin</option>
                <option value="operator">operator</option>
                <option value="viewer">viewer</option>
              </Select>
            </div>
            {updateRole !== 'admin' ? (
              <div>
                <Label htmlFor="update-tenant-id">tenant_id</Label>
                <Select id="update-tenant-id" {...updateForm.register('tenant_id')}>
                  <option value="">Tenant 선택</option>
                  {(tenantsQuery.data?.items ?? []).map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name} ({tenant.key})
                    </option>
                  ))}
                </Select>
                {updateForm.formState.errors.tenant_id?.message ? (
                  <p className="mt-1 text-xs text-destructive">{updateForm.formState.errors.tenant_id.message}</p>
                ) : null}
              </div>
            ) : null}
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...updateForm.register('is_active')} />
              활성 상태
            </label>
            <div>
              <Label htmlFor="update-password">비밀번호 변경 (선택)</Label>
              <Input id="update-password" type="password" {...updateForm.register('password')} />
              {updateForm.formState.errors.password?.message ? (
                <p className="mt-1 text-xs text-destructive">{updateForm.formState.errors.password.message}</p>
              ) : null}
            </div>
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

      <Dialog open={Boolean(deactivateTarget)} onOpenChange={(open) => !open && setDeactivateTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>사용자 비활성화</DialogTitle>
            <DialogDescription>
              안전 확인을 위해 대상 사용자 ID를 직접 입력하세요. (자기 자신은 비활성화할 수 없습니다.)
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md bg-muted p-3 text-sm">
              대상: <strong>{deactivateTarget?.username}</strong> / <span className="font-mono">{deactivateTarget?.id}</span>
            </div>
            <div>
              <Label htmlFor="deactivate-confirm">확인 입력</Label>
              <Input
                id="deactivate-confirm"
                value={deactivateConfirm}
                onChange={(event) => setDeactivateConfirm(event.target.value)}
                placeholder="대상 ID를 그대로 입력"
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDeactivateTarget(null)}>
                취소
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={deactivateMutation.isPending}
                onClick={onDeactivate}
              >
                {deactivateMutation.isPending ? '처리 중...' : '비활성화'}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
