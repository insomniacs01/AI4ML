const CACHE_PREFIX = 'ai4ml-workspace-cache'
const CACHE_VERSION = 1
const MAX_CACHE_AGE_MS = 24 * 60 * 60 * 1000
const RUNTIME_CACHE_FRESH_MS = 30 * 1000
const TASK_DETAIL_ONLY_KEYS = [
  'dataset_profile',
  'analysis_token_usage',
  'last_run',
  'last_run_attempt',
  'structured_requirements',
  'stage_routing',
  'interaction_policies',
]

export function workspaceCacheKey(context = {}) {
  const { userId, teamId } = context || {}
  if (!userId || !teamId) return ''
  return `${CACHE_PREFIX}:${userId}:${teamId}`
}

export function readWorkspaceCache(context, now = Date.now()) {
  const key = workspaceCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return null
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || 'null')
    if (!parsed || parsed.version !== CACHE_VERSION) return null
    if (!Number.isFinite(parsed.cachedAt) || now - parsed.cachedAt > MAX_CACHE_AGE_MS) return null
    return compactWorkspaceSnapshot(parsed)
  } catch {
    return null
  }
}

export function writeWorkspaceCache(context, snapshot, now = Date.now()) {
  const key = workspaceCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return false
  const payload = {
    version: CACHE_VERSION,
    userId: context.userId,
    teamId: context.teamId,
    cachedAt: now,
    tasks: Array.isArray(snapshot?.tasks) ? snapshot.tasks.map(compactTaskRecord) : [],
    activeTaskId: snapshot?.activeTaskId || '',
    task: compactTaskRecord(snapshot?.task),
    taskRun: compactTaskRun(snapshot?.taskRun),
    steps: Array.isArray(snapshot?.steps) ? snapshot.steps : [],
  }
  try {
    localStorage.setItem(key, JSON.stringify(payload))
    return true
  } catch {
    return false
  }
}

export function workspaceCacheAgeText(cachedAt, now = Date.now()) {
  if (!Number.isFinite(cachedAt)) return ''
  const ageSeconds = Math.max(0, Math.round((now - cachedAt) / 1000))
  if (ageSeconds < 60) return `${ageSeconds} 秒前`
  const ageMinutes = Math.round(ageSeconds / 60)
  if (ageMinutes < 60) return `${ageMinutes} 分钟前`
  const ageHours = Math.round(ageMinutes / 60)
  return `${ageHours} 小时前`
}

export function isWorkspaceRuntimeCacheFresh(cachedAt, now = Date.now()) {
  return Number.isFinite(cachedAt) && now - cachedAt <= RUNTIME_CACHE_FRESH_MS
}

function compactWorkspaceSnapshot(snapshot) {
  return {
    ...snapshot,
    tasks: Array.isArray(snapshot.tasks) ? snapshot.tasks.map(compactTaskRecord) : [],
    task: compactTaskRecord(snapshot.task),
    taskRun: compactTaskRun(snapshot.taskRun),
    steps: Array.isArray(snapshot.steps) ? snapshot.steps : [],
  }
}

function compactTaskRecord(task) {
  if (!task || typeof task !== 'object') return null
  const compact = { ...task }
  TASK_DETAIL_ONLY_KEYS.forEach((key) => {
    delete compact[key]
  })
  return compact
}

function compactTaskRun(taskRun) {
  if (!taskRun || typeof taskRun !== 'object') return null
  const compact = { ...taskRun }
  if (compact.codex && typeof compact.codex === 'object') {
    compact.codex = { ...compact.codex }
    delete compact.codex.token_usage
  }
  return compact
}
