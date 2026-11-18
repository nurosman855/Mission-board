import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const requireRoleMock = vi.fn()
const runMock = vi.fn()
const prepareMock = vi.fn((_sql: string) => ({ run: runMock }))

vi.mock('@/lib/auth', () => ({ requireRole: requireRoleMock }))
vi.mock('@/lib/rate-limit', () => ({ mutationLimiter: () => null }))
vi.mock('@/lib/db', () => ({ getDatabase: () => ({ prepare: prepareMock }) }))
vi.mock('@/lib/logger', () => ({ logger: { error: vi.fn() } }))

const req = (token: string) => new NextRequest('http://localhost/api/tasks/42/lease', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ lease_token: token }),
})
const params = { params: Promise.resolve({ id: '42' }) }

describe('ClearPage server lease renewal', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    requireRoleMock.mockReturnValue({ user: { role: 'operator', agent_name: 'clearpage-researcher', workspace_id: 7 } })
  })

  it('renews a currently owned lease with a scoped atomic write', async () => {
    runMock.mockReturnValue({ changes: 1 })
    const { POST } = await import('@/app/api/tasks/[id]/lease/route')
    const response = await POST(req('b'.repeat(64)), params)
    expect(response.status).toBe(200)
    expect((await response.json()).renewed).toBe(true)
    expect(prepareMock.mock.calls[0][0]).toContain("t.status='in_progress'")
    expect(runMock).toHaveBeenCalledWith(expect.any(Number), 42, 7, 'clearpage-researcher',
      expect.stringMatching(/^[a-f0-9]{64}$/), expect.any(Number), 7, 'clearpage-researcher')
  })

  it('rejects expired or replaced fences', async () => {
    runMock.mockReturnValue({ changes: 0 })
    const { POST } = await import('@/app/api/tasks/[id]/lease/route')
    expect((await POST(req('b'.repeat(64)), params)).status).toBe(409)
  })

  it('denies admin override and invalid tokens on the worker renewal endpoint', async () => {
    const { POST } = await import('@/app/api/tasks/[id]/lease/route')
    requireRoleMock.mockReturnValue({ user: { role: 'admin', workspace_id: 7 } })
    expect((await POST(req('b'.repeat(64)), params)).status).toBe(403)
    requireRoleMock.mockReturnValue({ user: { role: 'operator', agent_name: 'clearpage-validator', workspace_id: 7 } })
    expect((await POST(req('invalid'), params)).status).toBe(400)
    expect(prepareMock).not.toHaveBeenCalled()
  })
})
