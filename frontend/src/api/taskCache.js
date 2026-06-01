import { optionalRequest } from '@/api/request'

let lastTaskCacheWarmupAt = 0

export function warmupTaskCache() {
  return optionalRequest('/tasks/cache/warmup', { method: 'POST', body: JSON.stringify({}) }, { warmed: false })
}

export function warmupTaskCacheSoon() {
  const now = Date.now()
  if (now - lastTaskCacheWarmupAt < 30_000) return
  lastTaskCacheWarmupAt = now
  globalThis.setTimeout(() => {
    warmupTaskCache().catch(() => {})
  }, 0)
}
