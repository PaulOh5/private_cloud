import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InstanceDetailPage } from '@/pages/instance-detail-page'

const getInstanceMock = vi.fn()
const issueConsoleTicketMock = vi.fn()
const listTasksMock = vi.fn()
const useAuthMock = vi.fn()

const rfbState = vi.hoisted(() => {
  class MockRFB {
    static instances: MockRFB[] = []
    static constructorCalls: Array<{ target: HTMLElement; url: string; options?: Record<string, unknown> }> = []

    scaleViewport = false
    resizeSession = false
    disconnect = vi.fn()
    addEventListener = vi.fn()

    constructor(target: HTMLElement, url: string, options?: Record<string, unknown>) {
      MockRFB.instances.push(this)
      MockRFB.constructorCalls.push({ target, url, options })
    }
  }

  return { MockRFB }
})

vi.mock('@/features/instances/api', () => ({
  getInstance: (...args: unknown[]) => getInstanceMock(...args),
  issueConsoleTicket: (...args: unknown[]) => issueConsoleTicketMock(...args),
}))

vi.mock('@/features/tasks/api', () => ({
  listTasks: (...args: unknown[]) => listTasksMock(...args),
}))

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: () => useAuthMock(),
}))

vi.mock('@novnc/novnc/lib/rfb', () => ({
  default: rfbState.MockRFB,
}))

const baseInstance = {
  id: 'instance-1',
  name: 'vm-1',
  cpu: 2,
  memory_mib: 2048,
  disk_gib: 20,
  status: 'running',
  ip_address: '172.30.10.10',
  host_node: 'localhost',
  created_at: '2026-02-01T00:00:00Z',
  updated_at: '2026-02-01T00:00:00Z',
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/instances/instance-1']}>
        <Routes>
          <Route path="/instances/:instanceId" element={<InstanceDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('InstanceDetailPage console card', () => {
  beforeEach(() => {
    getInstanceMock.mockReset()
    issueConsoleTicketMock.mockReset()
    listTasksMock.mockReset()
    useAuthMock.mockReset()
    rfbState.MockRFB.instances = []
    rfbState.MockRFB.constructorCalls = []
    useAuthMock.mockReturnValue({
      hasAnyRole: (...roles: string[]) => roles.includes('operator'),
    })
    listTasksMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    issueConsoleTicketMock.mockResolvedValue({
      ticket: 'ticket-1',
      expires_at: '2099-01-01T00:00:00Z',
      websocket_path: '/instances/instance-1/console/ws?ticket=ticket-1',
    })
  })

  it('enables connect button when instance is running', async () => {
    getInstanceMock.mockResolvedValue({ ...baseInstance, status: 'running' })

    renderPage()

    const connectButton = await screen.findByRole('button', { name: '콘솔 연결' })
    expect(connectButton).toBeEnabled()
  })

  it('disables connect button when instance is not running', async () => {
    getInstanceMock.mockResolvedValue({ ...baseInstance, status: 'stopped' })

    renderPage()

    const connectButton = await screen.findByRole('button', { name: '콘솔 연결' })
    expect(connectButton).toBeDisabled()
    expect(screen.getByText(/현재 상태가 중지됨이므로 콘솔 접속이 비활성화됩니다./)).toBeInTheDocument()
  })

  it('disables connect button for viewer role', async () => {
    getInstanceMock.mockResolvedValue({ ...baseInstance, status: 'running' })
    useAuthMock.mockReturnValue({
      hasAnyRole: () => false,
    })

    renderPage()

    const connectButton = await screen.findByRole('button', { name: '콘솔 연결' })
    expect(connectButton).toBeDisabled()
    expect(screen.getByText(/콘솔 접속 권한이 없습니다/)).toBeInTheDocument()
  })

  it('requests ticket and initializes noVNC on connect', async () => {
    getInstanceMock.mockResolvedValue({ ...baseInstance, status: 'running' })
    const user = userEvent.setup()

    renderPage()

    const connectButton = await screen.findByRole('button', { name: '콘솔 연결' })
    await user.click(connectButton)

    await waitFor(() => {
      expect(issueConsoleTicketMock).toHaveBeenCalledWith('instance-1')
    })
    expect(rfbState.MockRFB.constructorCalls).toHaveLength(1)
    expect(rfbState.MockRFB.constructorCalls[0]?.url).toMatch(
      /^ws:\/\/localhost(:\d+)?\/api\/instances\/instance-1\/console\/ws\?ticket=ticket-1$/,
    )
    expect(rfbState.MockRFB.constructorCalls[0]?.options).toEqual({ wsProtocols: ['binary'] })
  })

  it('disconnects noVNC session on unmount', async () => {
    getInstanceMock.mockResolvedValue({ ...baseInstance, status: 'running' })
    const user = userEvent.setup()

    const rendered = renderPage()
    const connectButton = await screen.findByRole('button', { name: '콘솔 연결' })
    await user.click(connectButton)

    await waitFor(() => {
      expect(rfbState.MockRFB.instances).toHaveLength(1)
    })

    rendered.unmount()
    expect(rfbState.MockRFB.instances[0]?.disconnect).toHaveBeenCalled()
  })
})
