import { createHash } from 'crypto'
import { NextRequest, NextResponse } from 'next/server'
import { requireRole } from '@/lib/auth'
import { getDatabase } from '@/lib/db'
import { mutationLimiter } from '@/lib/rate-limit'
import { logger } from '@/lib/logger'
import { requireWorkspaceId } from '@/lib/enforcement/workspace-scope'

/** Extend only an existing, unexpired ClearPage worker submission fence. */
export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = requireRole(request, 'operator')
  if ('error' in auth) return NextResponse.json({ error: auth.error }, { status: auth.status })
  const limited = mutationLimiter(request)
  if (limited) return limited

  const agent = auth.user.agent_name
  if (auth.user.role === 'admin' || !['clearpage-researcher', 'clearpage-validator'].includes(agent || '')) {
    return NextResponse.json({ error: 'Only a scoped ClearPage worker can renew its lease' }, { status: 403 })
  }
  const ws = requireWorkspaceId(auth.user)
  if (!('workspaceId' in ws)) return ws.response
  const { id } = await params
  if (!/^[1-9]\d*$/.test(id) || !Number.isSafeInteger(Number(id))) {
    return NextResponse.json({ error: 'Invalid task ID' }, { status: 400 })
  }
  let payload: unknown
  try { payload = await request.json() } catch { return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 }) }
  const token = typeof payload === 'object' && payload !== null && !Array.isArray(payload)
    ? (payload as Record<string, unknown>).lease_token : null
  if (typeof token !== 'string' || !/^[a-f0-9]{64}$/.test(token)) {
    return NextResponse.json({ error: 'Valid task lease token required' }, { status: 400 })
  }
  try {
    const now = Math.floor(Date.now() / 1000)
    const expiresAt = now + 120
    const db = getDatabase()
    const updated = db.prepare(`UPDATE clearpage_task_fences SET expires_at = ?
      WHERE task_id = ? AND workspace_id = ? AND agent_name = ?
        AND token_hash = ? AND expires_at > ?
        AND EXISTS (SELECT 1 FROM tasks t WHERE t.id=clearpage_task_fences.task_id
          AND t.workspace_id=? AND t.assigned_to=? AND t.status='in_progress')`).run(
      expiresAt, Number(id), ws.workspaceId, agent, createHash('sha256').update(token).digest('hex'),
      now, ws.workspaceId, agent,
    )
    if (updated.changes !== 1) {
      return NextResponse.json({ error: 'Task lease expired, replaced, or unavailable' }, { status: 409 })
    }
    return NextResponse.json({ task_id: Number(id), lease_expires_at: expiresAt, renewed: true })
  } catch (error) {
    logger.error({ err: error }, 'POST /api/tasks/[id]/lease error')
    return NextResponse.json({ error: 'Failed to renew task lease' }, { status: 500 })
  }
}
