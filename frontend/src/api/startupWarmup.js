const STARTUP_WARMUP_TTL_MS = 60 * 1000
let lastAuthenticatedWarmupAt = 0

export function warmupAuthenticatedExperienceSoon(options = {}) {
  const now = Date.now()
  if (now - lastAuthenticatedWarmupAt < STARTUP_WARMUP_TTL_MS) return
  lastAuthenticatedWarmupAt = now

  warmupRouteChunksSoon(6000)
}

function warmupRouteChunksSoon(delayMs = 0) {
  scheduleWarmup(delayMs, () => {
    return Promise.allSettled([
      import('@/views/CreateTaskView.vue'),
      import('@/views/TasksView.vue'),
      import('@/views/WorkspaceView.vue'),
      import('@/views/CommunityView.vue'),
      import('@/views/TaskDetailView.vue'),
      import('@/views/ProfileView.vue'),
      import('@/views/MyAssetsView.vue'),
      import('@/views/AdminView.vue'),
    ])
  })
}

function scheduleWarmup(delayMs, action) {
  globalThis.setTimeout(() => {
    const result = action()
    if (result && typeof result.catch === 'function') {
      result.catch(() => {})
    }
  }, delayMs)
}
