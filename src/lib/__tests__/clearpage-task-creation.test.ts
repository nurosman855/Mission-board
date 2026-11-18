import { describe, it, expect, vi } from 'vitest'
import { mayAgentCreateTask } from '@/lib/enforcement/clearpage-task-creation'
import type { User } from '@/lib/auth'
import type Database from 'better-sqlite3'

const user = (name: string, role: 'operator' | 'admin' = 'operator') =>
  ({ agent_name: name, role }) as User

describe('ClearPage task-creation scope', () => {
  const db = (found: boolean) => ({
    prepare: vi.fn(() => ({ get: vi.fn(() => found ? { id: 4 } : undefined) })),
  }) as unknown as Database.Database

  it('allows Researcher self-assignment but forbids Validator self-scheduling', () => {
    const database = db(false)
    expect(mayAgentCreateTask(database, user('clearpage-researcher'), 7, 'clearpage-researcher', {})).toBe(true)
    expect(mayAgentCreateTask(database, user('clearpage-validator'), 7, 'clearpage-validator', {})).toBe(false)
    expect(database.prepare).not.toHaveBeenCalled()
  })

  it('denies arbitrary cross-agent task creation', () => {
    const database = db(true)
    expect(mayAgentCreateTask(database, user('clearpage-validator'), 7, 'clearpage-researcher', {})).toBe(false)
    expect(mayAgentCreateTask(database, user('clearpage-researcher'), 7, 'clearpage-strategist', {})).toBe(false)
    expect(mayAgentCreateTask(database, user('other-agent'), 7, 'clearpage-validator', {})).toBe(false)
    expect(database.prepare).not.toHaveBeenCalled()
  })

  it('only permits a simulation Validator handoff linked to a reviewed Researcher task', () => {
    const metadata = { stage: 'validation', simulation_only: true,
      clearpage_run_id: 'run-1', research_task_id: 4 }
    const denied = db(false)
    expect(mayAgentCreateTask(denied, user('clearpage-researcher'), 7, 'clearpage-validator', metadata)).toBe(false)
    const allowed = db(true)
    expect(mayAgentCreateTask(allowed, user('clearpage-researcher'), 7, 'clearpage-validator', metadata)).toBe(true)
    expect(allowed.prepare).toHaveBeenCalledWith(expect.stringContaining("AND assigned_to = 'clearpage-researcher' AND status = 'review'"))
    expect(mayAgentCreateTask(db(true), user('clearpage-researcher'), 7, 'clearpage-validator',
      { ...metadata, simulation_only: false })).toBe(false)
  })
})
