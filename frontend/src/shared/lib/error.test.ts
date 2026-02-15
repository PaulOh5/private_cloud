import axios, { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'

import { resolveErrorMessage } from '@/shared/lib/error'

describe('resolveErrorMessage', () => {
  it('returns detail when FastAPI error format is used', () => {
    const error = new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
      data: { detail: 'invalid credentials' },
      status: 401,
      statusText: 'Unauthorized',
      headers: {},
      config: { headers: new axios.AxiosHeaders() },
    })

    expect(resolveErrorMessage(error)).toBe('invalid credentials')
  })

  it('returns domain message when available', () => {
    const error = new AxiosError('Conflict', 'ERR_BAD_REQUEST', undefined, undefined, {
      data: { code: 'CONFLICT', message: 'instance already exists' },
      status: 409,
      statusText: 'Conflict',
      headers: {},
      config: { headers: new axios.AxiosHeaders() },
    })

    expect(resolveErrorMessage(error)).toBe('instance already exists')
  })

  it('returns fallback for unknown error', () => {
    expect(resolveErrorMessage(new Error('boom'))).toBe('알 수 없는 오류가 발생했습니다.')
  })
})
