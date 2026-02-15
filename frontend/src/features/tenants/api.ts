import { apiClient } from '@/lib/api/client'
import type { PaginationResponse, Tenant, TenantQuota, TenantUsage } from '@/types/api'

export interface ListTenantsParams {
  limit: number
  offset: number
  is_active?: boolean
}

export interface CreateTenantPayload {
  key: string
  name: string
  is_active: boolean
  max_instances: number
  max_cpu: number
  max_memory_mib: number
  max_disk_gib: number
}

export interface UpdateTenantPayload {
  name?: string
  is_active?: boolean
}

export interface UpdateTenantQuotaPayload {
  max_instances: number
  max_cpu: number
  max_memory_mib: number
  max_disk_gib: number
}

export async function listTenants(params: ListTenantsParams): Promise<PaginationResponse<Tenant>> {
  const response = await apiClient.get<PaginationResponse<Tenant>>('/tenants', { params })
  return response.data
}

export async function getTenant(tenantId: string): Promise<Tenant> {
  const response = await apiClient.get<Tenant>(`/tenants/${tenantId}`)
  return response.data
}

export async function createTenant(payload: CreateTenantPayload): Promise<Tenant> {
  const response = await apiClient.post<Tenant>('/tenants', payload)
  return response.data
}

export async function updateTenant(tenantId: string, payload: UpdateTenantPayload): Promise<Tenant> {
  const response = await apiClient.patch<Tenant>(`/tenants/${tenantId}`, payload)
  return response.data
}

export async function updateTenantQuota(tenantId: string, payload: UpdateTenantQuotaPayload): Promise<TenantQuota> {
  const response = await apiClient.patch<TenantQuota>(`/tenants/${tenantId}/quota`, payload)
  return response.data
}

export async function getTenantUsage(tenantId: string): Promise<TenantUsage> {
  const response = await apiClient.get<TenantUsage>(`/tenants/${tenantId}/usage`)
  return response.data
}

export async function deleteTenant(tenantId: string): Promise<void> {
  await apiClient.delete(`/tenants/${tenantId}`)
}
