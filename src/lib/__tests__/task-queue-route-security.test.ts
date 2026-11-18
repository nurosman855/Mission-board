import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const requireRoleMock = vi.fn()
const agentTaskLimiterMock = vi.fn(() => null)
const prepareMock = vi.fn()

vi.mock('@/lib/auth', () => ({ requireRole: requireRoleMock }))
vi.mock('@/lib/rate-limit', () => ({ agentTaskLimiter: agentTaskLimiterMock }))
vi.mock('@/lib/logger', () => ({ logger: { error: vi.fn(), warn: vi.fn(), info: vi.fn() } }))
vi.mock('@/lib/db', () => ({
  getDatabase: vi.fn(() => ({ prepare: prepareMock })),
}))

describe('task queue route security', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    agentTaskLimiterMock.mockReturnValue(null)
  })

  it('GET fails closed when workspace_id is missing', async () => {
    requireRoleMock.mockReturnValue({
      user: { username: 'agent-a', role: 'operator', agent_name: 'agent-a' },
    })

    const { GET } = await import('@/app/api/tasks/queue/route')
    const response = await GET(
      new NextRequest('http://localhost/api/tasks/queue?agent=agent-a'),
    )

    expect(response.status).toBe(400)
    await expect(response.json()).resolves.toEqual({ error: 'Workspace context required' })
    expect(prepareMock).not.toHaveBeenCalled()
  })

  it('GET denies agent overreach when queueing for another agent', async () => {
    requireRoleMock.mockReturnValue({
      user: { username: 'agent-a', role: 'operator', agent_name: 'agent-a', workspace_id: 7 },
    })

    const { GET } = await import('@/app/api/tasks/queue/route')
    const response = await GET(
      new NextRequest('http://localhost/api/tasks/queue?agent=agent-b'),
    )

    expect(response.status).toBe(403)
    await expect(response.json()).resolves.toEqual({
      error: 'Access denied: agent key may only queue tasks for itself.',
    })
    expect(prepareMock).not.toHaveBeenCalled()
  })

  it('rejects invalid explicit task IDs before touching the database', async () => {
    requireRoleMock.mockReturnValue({ user: { role: 'operator', agent_name: 'agent-a', workspace_id: 7 } })
    const { GET } = await import('@/app/api/tasks/queue/route')
    for (const value of ['0', '-1', '1.2', '999999999999999999999']) {
      const response = await GET(new NextRequest(`http://localhost/api/tasks/queue?agent=agent-a&task_id=${value}`))
      expect(response.status).toBe(400)
    }
    expect(prepareMock).not.toHaveBeenCalled()
  })

  it('claims only the exact assigned task ID with an atomic scoped update', async () => {
    requireRoleMock.mockReturnValue({ user: { role: 'operator', agent_name: 'agent-a', workspace_id: 7 } })
    const updateGet = vi.fn().mockReturnValue({ id: 9, assigned_to: 'agent-a', status: 'in_progress', tags: '[]', metadata: '{}' })
    prepareMock.mockImplementation((sql: string) => {
      if (sql.includes('COUNT(*)')) return { get: () => ({ c: 0 }) }
      if (sql.includes('UPDATE tasks')) return { get: updateGet }
      return { get: () => undefined }
    })
    const { GET } = await import('@/app/api/tasks/queue/route')
    const response = await GET(new NextRequest('http://localhost/api/tasks/queue?agent=agent-a&task_id=9'))
    expect(response.status).toBe(200)
    expect((await response.json()).task.id).toBe(9)
    const updateSql = prepareMock.mock.calls.map(call => call[0]).find((sql: string) => sql.includes('UPDATE tasks'))
    expect(updateSql).toContain("id = ? AND workspace_id = ? AND assigned_to = ? AND status = 'assigned'")
    expect(updateGet).toHaveBeenCalledWith(expect.any(Number), 9, 7, 'agent-a')
  })

  it('does not claim another task when the requested ID is unavailable', async () => {
    requireRoleMock.mockReturnValue({ user: { role: 'operator', agent_name: 'agent-a', workspace_id: 7 } })
    prepareMock.mockImplementation((sql: string) => {
      if (sql.includes('COUNT(*)')) return { get: () => ({ c: 0 }) }
      return { get: () => undefined }
    })
    const { GET } = await import('@/app/api/tasks/queue/route')
    const response = await GET(new NextRequest('http://localhost/api/tasks/queue?agent=agent-a&task_id=9'))
    expect(response.status).toBe(409)
    expect((await response.json()).task).toBeNull()
    expect(prepareMock.mock.calls.filter(call => (call[0] as string).includes('UPDATE tasks'))).toHaveLength(1)
  })
})
