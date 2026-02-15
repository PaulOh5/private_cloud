export type Role = 'admin' | 'operator' | 'viewer'

export type InstanceStatus =
  | 'creating_pending'
  | 'updating_pending'
  | 'deleting_pending'
  | 'running'
  | 'stopped'
  | 'error'
  | 'deleted'

export type TaskStatus = 'queued' | 'running' | 'cancel_pending' | 'succeeded' | 'failed' | 'canceled'
export type TaskCommand = 'create' | 'update' | 'delete'

export interface PaginationResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Instance {
  id: string
  name: string | null
  cpu: number
  memory_mib: number
  disk_gib: number
  status: InstanceStatus
  ip_address: string | null
  host_node: string
  created_at: string
  updated_at: string
}

export interface Task {
  id: string
  instance_id: string
  command: TaskCommand
  status: TaskStatus
  request_id: string
  request_payload: Record<string, unknown>
  result_payload: Record<string, unknown> | null
  error_code: string | null
  error_message: string | null
  attempt_count: number
  max_attempts: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export interface TaskAccepted {
  task_id: string
  instance_id: string
  status: TaskStatus
  command: TaskCommand
  accepted_at: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_at: string
}

export interface CurrentUser {
  id: string
  username: string
  role: Role
  is_active: boolean
}

export interface RefreshTokenRequest {
  refresh_token: string
}

export interface RoleItem {
  name: Role
}

export interface RolesResponse {
  items: RoleItem[]
}

export interface User {
  id: string
  username: string
  role: Role
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface CreateUserRequest {
  username: string
  password: string
  role: Role
  is_active: boolean
}

export interface UpdateUserRequest {
  role?: Role
  is_active?: boolean
  password?: string
}

export interface AuditLog {
  id: string
  actor_user_id: string | null
  actor_username: string | null
  action: string
  target_type: string
  target_id: string | null
  request_id: string | null
  ip_address: string | null
  user_agent: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface FastApiError {
  detail: string
}

export interface DomainError {
  code: string
  message: string
}
