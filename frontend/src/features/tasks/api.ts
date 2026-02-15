import { apiClient } from '@/lib/api/client'
import type { PaginationResponse, Task } from '@/types/api'

export interface ListTasksParams {
  limit: number
  offset: number
  status?: string
  instance_id?: string
  command?: string
  tenant_id?: string
}

export async function listTasks(params: ListTasksParams): Promise<PaginationResponse<Task>> {
  const response = await apiClient.get<PaginationResponse<Task>>('/tasks', { params })
  return response.data
}

export async function getTask(taskId: string): Promise<Task> {
  const response = await apiClient.get<Task>(`/tasks/${taskId}`)
  return response.data
}
