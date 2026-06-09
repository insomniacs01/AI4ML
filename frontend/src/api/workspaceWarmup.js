import { getTaskRuntimeSnapshot, getWorkspaceTasks } from '@/api/tasks'
import { getActiveTeamHint, getCachedUser } from '@/api/session'
import { pickActiveTask, taskIdOf } from '@/utils/taskRecords'
import { writeWorkspaceCache } from '@/utils/workspaceCache'

let lastWorkspaceWarmupAt = 0
let warmupTimer = null

const WORKSPACE_WARMUP_TTL_MS = 30_000

export function warmupWorkspaceCacheSoon(delayMs = 0) {
  const now = Date.now()
  if (now - lastWorkspaceWarmupAt < WORKSPACE_WARMUP_TTL_MS || warmupTimer) return
  warmupTimer = globalThis.setTimeout(() => {
    warmupTimer = null
    warmupWorkspaceCache().catch(() => {})
  }, delayMs)
}

export async function warmupWorkspaceCache() {
  const context = workspaceCacheContext()
  if (!context) return false
  lastWorkspaceWarmupAt = Date.now()
  const tasks = await getWorkspaceTasks()
  const activeTask = pickActiveTask(tasks)
  const activeTaskId = taskIdOf(activeTask)
  let task = activeTask || null
  let taskRun = null
  let steps = []

  if (activeTaskId) {
    const detail = await getTaskRuntimeSnapshot(activeTaskId, { sync: false, taskDetail: 'summary' })
    task = detail.task || task
    taskRun = detail.task_run || null
    steps = Array.isArray(detail.task_run?.steps) ? detail.task_run.steps : []
  }

  return writeWorkspaceCache(context, {
    tasks,
    activeTaskId,
    task,
    taskRun,
    steps,
  })
}

function workspaceCacheContext() {
  const userId = getCachedUser()?.id
  const teamId = getActiveTeamHint()?.id
  return userId && teamId ? { userId, teamId } : null
}
