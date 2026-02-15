import { apiClient } from '@/lib/api/client'
import type { ConsoleTicketResponse, Instance, PaginationResponse, TaskAccepted, VmImage } from '@/types/api'

export interface ListInstancesParams {
  limit: number
  offset: number
  status?: string
  name?: string
}

export interface CreateInstancePayload {
  name?: string
  cpu: number
  memory_mib: number
  disk_gib: number
  image_id?: string
}

export interface UpdateInstancePayload {
  cpu: number
  memory_mib: number
  disk_gib: number
}

export async function listInstances(params: ListInstancesParams): Promise<PaginationResponse<Instance>> {
  const response = await apiClient.get<PaginationResponse<Instance>>('/instances', { params })
  return response.data
}

export async function getInstance(instanceId: string): Promise<Instance> {
  const response = await apiClient.get<Instance>(`/instances/${instanceId}`)
  return response.data
}

export async function createInstance(payload: CreateInstancePayload): Promise<TaskAccepted> {
  const response = await apiClient.post<TaskAccepted>('/instances', payload)
  return response.data
}

export async function updateInstance(instanceId: string, payload: UpdateInstancePayload): Promise<TaskAccepted> {
  const response = await apiClient.put<TaskAccepted>(`/instances/${instanceId}`, payload)
  return response.data
}

export async function deleteInstance(instanceId: string): Promise<TaskAccepted> {
  const response = await apiClient.delete<TaskAccepted>(`/instances/${instanceId}`)
  return response.data
}

export async function issueConsoleTicket(instanceId: string): Promise<ConsoleTicketResponse> {
  const response = await apiClient.post<ConsoleTicketResponse>(`/instances/${instanceId}/console-ticket`)
  return response.data
}

export async function listVmImages(): Promise<VmImage[]> {
  const response = await apiClient.get<{ items: VmImage[] }>('/images')
  return response.data.items
}
