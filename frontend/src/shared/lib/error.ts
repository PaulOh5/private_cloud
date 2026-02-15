import axios from 'axios'

import type { DomainError, FastApiError } from '@/types/api'

function hasDetail(payload: unknown): payload is FastApiError {
  return typeof payload === 'object' && payload !== null && 'detail' in payload
}

function hasDomainMessage(payload: unknown): payload is DomainError {
  return typeof payload === 'object' && payload !== null && 'message' in payload
}

export function resolveErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error)) {
    return '알 수 없는 오류가 발생했습니다.'
  }

  const payload = error.response?.data

  if (hasDetail(payload) && typeof payload.detail === 'string') {
    return payload.detail
  }

  if (hasDomainMessage(payload) && typeof payload.message === 'string') {
    return payload.message
  }

  if (error.response?.status === 401) {
    return '인증이 만료되었거나 유효하지 않습니다.'
  }

  if (error.response?.status === 403) {
    return '이 작업을 수행할 권한이 없습니다.'
  }

  if (error.response?.status === 404) {
    return '요청한 리소스를 찾을 수 없습니다.'
  }

  if (error.response?.status === 409) {
    return '현재 상태에서 처리할 수 없어 충돌이 발생했습니다.'
  }

  return error.message || '요청 처리 중 오류가 발생했습니다.'
}
