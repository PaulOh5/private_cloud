import { apiClient } from '@/lib/api/client'
import type { AuditLog, PaginationResponse } from '@/types/api'

export interface ListAuditLogsParams {
  limit: number
  offset: number
  actor_user_id?: string
  action?: string
  target_type?: string
  request_id?: string
  tenant_id?: string
}

export async function listAuditLogs(params: ListAuditLogsParams): Promise<PaginationResponse<AuditLog>> {
  const response = await apiClient.get<PaginationResponse<AuditLog>>('/audit-logs', { params })
  return response.data
}

export async function getAuditLog(logId: string): Promise<AuditLog> {
  const response = await apiClient.get<AuditLog>(`/audit-logs/${logId}`)
  return response.data
}
