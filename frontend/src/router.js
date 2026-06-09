import { createRouter, createWebHistory } from 'vue-router'
import { getMe } from './api/auth'
import { requireSession } from './api/session'

const AUTH_CACHE_TTL_MS = 30_000
const AUTH_SESSION_TIMEOUT_MS = 2_500
const AUTH_PROFILE_TIMEOUT_MS = 5_000
let authCache = null
let authCheckedAt = 0
let sessionCache = null
let sessionCheckedAt = 0

export function clearAuthCache() {
  authCache = null
  authCheckedAt = 0
  sessionCache = null
  sessionCheckedAt = 0
}

function timeoutAfter(ms) {
  return new Promise((_, reject) => {
    globalThis.setTimeout(() => reject(new Error('auth timeout')), ms)
  })
}

async function loadAuthSession() {
  const now = Date.now()
  if (sessionCache && now - sessionCheckedAt < AUTH_CACHE_TTL_MS) return sessionCache
  try {
    sessionCache = await Promise.race([requireSession(), timeoutAfter(AUTH_SESSION_TIMEOUT_MS)])
    sessionCheckedAt = Date.now()
    return sessionCache
  } catch {
    clearAuthCache()
    return null
  }
}

async function loadAuthMe() {
  const now = Date.now()
  if (authCache && now - authCheckedAt < AUTH_CACHE_TTL_MS) return authCache

  try {
    authCache = await Promise.race([getMe(), timeoutAfter(AUTH_PROFILE_TIMEOUT_MS)])
    authCheckedAt = Date.now()
    return authCache
  } catch {
    clearAuthCache()
    return null
  }
}

const routes = [
  { path: '/', redirect: '/workspace' },
  { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
  { path: '/workspace', component: () => import('./views/WorkspaceView.vue') },
  { path: '/create', component: () => import('./views/CreateTaskView.vue') },
  { path: '/tasks', component: () => import('./views/TasksView.vue') },
  { path: '/tasks/:taskId/progress', component: () => import('./views/TaskProgressView.vue'), props: true },
  { path: '/tasks/:taskId', component: () => import('./views/TaskDetailView.vue'), props: true },
  { path: '/demo/:taskId', component: () => import('./views/TaskDemoView.vue'), props: true },
  { path: '/public-demo/:deploymentId', component: () => import('./views/PublicDemoView.vue'), props: true, meta: { public: true } },
  { path: '/community', component: () => import('./views/CommunityView.vue') },
  { path: '/profile', component: () => import('./views/ProfileView.vue') },
  { path: '/account', redirect: '/profile' },
  { path: '/assets', component: () => import('./views/MyAssetsView.vue') },
  { path: '/admin', component: () => import('./views/AdminView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/workspace' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.onError((error, to) => {
  const message = String(error?.message || error || '')
  const chunkLoadFailed = [
    'Failed to fetch dynamically imported module',
    'Importing a module script failed',
    'error loading dynamically imported module',
    'Loading chunk',
    'Unable to preload CSS',
  ].some((text) => message.includes(text))
  if (!chunkLoadFailed || typeof window === 'undefined') return

  const key = `ai4ml:chunk-reload:${to.fullPath}`
  if (window.sessionStorage.getItem(key)) return
  window.sessionStorage.setItem(key, '1')
  window.location.assign(to.fullPath)
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  try {
    const session = await loadAuthSession()
    if (!session) return `/login?next=${encodeURIComponent(to.fullPath)}`
    if (to.path === '/admin') {
      const data = await loadAuthMe()
      if (data?.user?.role !== 'admin') return '/workspace'
    }
    return true
  } catch {
    return `/login?next=${encodeURIComponent(to.fullPath)}`
  }
})

export default router
