import { optionalRequest } from '@/api/request'

let lastTaskCacheWarmupAt = 0
let taskCacheWarmupTimer = null

export function warmupTaskCache() {
  return optionalRequest('/tasks/cache/warmup', { method: 'POST', body: JSON.stringify({}) }, { warmed: false })
}

export function warmupTaskCacheSoon(delayMs = 12000) {
  const now = Date.now()
  if (now - lastTaskCacheWarmupAt < 30_000 || taskCacheWarmupTimer) return
  taskCacheWarmupTimer = globalThis.setTimeout(() => {
    taskCacheWarmupTimer = null
    lastTaskCacheWarmupAt = Date.now()
    warmupTaskCache().catch(() => {})
  }, delayMs)
}
