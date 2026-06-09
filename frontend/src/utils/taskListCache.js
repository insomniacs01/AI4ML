const CACHE_PREFIX = 'ai4ml-task-list-cache'
const CACHE_VERSION = 1
const FRESH_CACHE_MS = 60 * 1000
const MAX_CACHE_AGE_MS = 24 * 60 * 60 * 1000
const TASK_DETAIL_ONLY_KEYS = [
  'dataset_profile',
  'analysis_token_usage',
  'last_run',
  'last_run_attempt',
  'structured_requirements',
  'stage_routing',
  'interaction_policies',
]

export function taskListCacheKey(context = {}) {
  const { userId, teamId } = context || {}
  if (!userId || !teamId) return ''
  return `${CACHE_PREFIX}:${userId}:${teamId}`
}

export function readTaskListCache(context, now = Date.now()) {
  const key = taskListCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return null
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || 'null')
    if (!parsed || parsed.version !== CACHE_VERSION) return null
    if (!Number.isFinite(parsed.cachedAt) || now - parsed.cachedAt > MAX_CACHE_AGE_MS) return null
    return {
      cachedAt: parsed.cachedAt,
      tasks: Array.isArray(parsed.tasks) ? parsed.tasks.map(compactTaskRecord) : [],
    }
  } catch {
    return null
  }
}

export function writeTaskListCache(context, tasks, now = Date.now()) {
  const key = taskListCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return false
  try {
    localStorage.setItem(key, JSON.stringify({
      version: CACHE_VERSION,
      userId: context.userId,
      teamId: context.teamId,
      cachedAt: now,
      tasks: Array.isArray(tasks) ? tasks.map(compactTaskRecord) : [],
    }))
    return true
  } catch {
    return false
  }
}

export function clearTaskListCache(context) {
  const key = taskListCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return
  localStorage.removeItem(key)
}

export function isTaskListCacheFresh(cachedAt, now = Date.now()) {
  return Number.isFinite(cachedAt) && now - cachedAt <= FRESH_CACHE_MS
}

function compactTaskRecord(task) {
  if (!task || typeof task !== 'object') return null
  const compact = { ...task }
  TASK_DETAIL_ONLY_KEYS.forEach((key) => {
    delete compact[key]
  })
  return compact
}
