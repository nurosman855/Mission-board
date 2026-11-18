import type Database from 'better-sqlite3'
import type { User } from '@/lib/auth'

/** Extra restriction on non-admin agent-scoped task creation. */
export function mayAgentCreateTask(
  db: Database.Database, user: User, workspaceId: number,
  assignedTo: string | null | undefined, metadata: Record<string, unknown>,
): boolean {
  if (!user.agent_name || user.role === 'admin') return true
  // Validator is a consumer of handoffs, never a self-scheduler. Otherwise it
  // could forge a linked validation task to gain read access to source packets.
  if (user.agent_name === 'clearpage-validator') return false
  if (assignedTo === user.agent_name) return true
  if (user.agent_name !== 'clearpage-researcher' || assignedTo !== 'clearpage-validator' ||
      metadata.stage !== 'validation' || metadata.simulation_only !== true ||
      typeof metadata.clearpage_run_id !== 'string' ||
      !Number.isSafeInteger(metadata.research_task_id) || Number(metadata.research_task_id) <= 0) {
    return false
  }
  const source = db.prepare(`SELECT id FROM tasks WHERE id = ? AND workspace_id = ?
    AND assigned_to = 'clearpage-researcher' AND status = 'review'
    AND json_extract(metadata, '$.clearpage_run_id') = ?
    AND json_extract(metadata, '$.stage') = 'research'
    AND json_extract(metadata, '$.simulation_only') = 1`).get(
    metadata.research_task_id, workspaceId, metadata.clearpage_run_id,
  )
  return !!source
}
