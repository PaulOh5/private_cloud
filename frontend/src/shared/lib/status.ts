import type { InstanceStatus, TaskStatus } from '@/types/api'

export const instanceStatusLabel: Record<InstanceStatus, string> = {
  creating_pending: '생성 대기',
  updating_pending: '수정 대기',
  deleting_pending: '삭제 대기',
  running: '실행 중',
  stopped: '중지됨',
  error: '오류',
  deleted: '삭제됨',
}

export const taskStatusLabel: Record<TaskStatus, string> = {
  queued: '대기',
  running: '실행 중',
  succeeded: '성공',
  failed: '실패',
}

export const statusTone: Record<string, 'neutral' | 'success' | 'warning' | 'danger'> = {
  creating_pending: 'warning',
  updating_pending: 'warning',
  deleting_pending: 'warning',
  running: 'success',
  stopped: 'neutral',
  error: 'danger',
  deleted: 'neutral',
  queued: 'warning',
  succeeded: 'success',
  failed: 'danger',
}
