import { apiClient } from '@/lib/api/client'
import type {
  CreateUserRequest,
  PaginationResponse,
  RolesResponse,
  UpdateUserRequest,
  User,
} from '@/types/api'

export interface ListUsersParams {
  limit: number
  offset: number
  role?: string
  is_active?: boolean
  username?: string
  tenant_id?: string
}

export async function listRoles(): Promise<RolesResponse> {
  const response = await apiClient.get<RolesResponse>('/roles')
  return response.data
}

export async function listUsers(params: ListUsersParams): Promise<PaginationResponse<User>> {
  const response = await apiClient.get<PaginationResponse<User>>('/users', { params })
  return response.data
}

export async function getUser(userId: string): Promise<User> {
  const response = await apiClient.get<User>(`/users/${userId}`)
  return response.data
}

export async function createUser(payload: CreateUserRequest): Promise<User> {
  const response = await apiClient.post<User>('/users', payload)
  return response.data
}

export async function updateUser(userId: string, payload: UpdateUserRequest): Promise<User> {
  const response = await apiClient.patch<User>(`/users/${userId}`, payload)
  return response.data
}

export async function deactivateUser(userId: string): Promise<void> {
  await apiClient.delete(`/users/${userId}`)
}
