import { getProfile } from '@/api/auth'
import { getActiveTeamHint, getCachedUser } from '@/api/session'
import { getTasks } from '@/api/tasks'

const NOTIFICATION_READ_KEY = 'ai4ml-read-system-notifications'
const NOTIFICATION_CACHE_PREFIX = 'ai4ml-notification-cache-v1'
const NOTIFICATION_CACHE_TTL_MS = 30 * 1000
const HUMAN_WAITING_STATUSES = new Set(['waiting_human', 'paused_for_review'])
let pendingNotificationRefresh = null
let lastNotificationWarmupAt = 0

export async function getNotifications(options = {}) {
  const cacheKey = notificationCacheKey()
  if (!options.forceRefresh) {
    const cached = readNotificationCache(cacheKey)
    if (cached) return cached
    if (pendingNotificationRefresh) return pendingNotificationRefresh
  }
  pendingNotificationRefresh = buildNotifications()
    .then((data) => {
      writeNotificationCache(cacheKey, data.items || [])
      return data
    })
    .finally(() => {
      pendingNotificationRefresh = null
    })
  return pendingNotificationRefresh
}

async function buildNotifications() {
  const [profile, tasks] = await Promise.all([
    getProfile(),
    getTasks({ runtimeOnly: true }),
  ])
  const readIds = readNotificationIds()
  const items = quotaNotificationsFromProfile(profile, readIds)

  for (const task of tasks.items || []) {
    if (!HUMAN_WAITING_STATUSES.has(task.status)) continue
    const taskId = task.task_id || task.id
    const id = `human-confirm:${profile.active_team_id}:${taskId}:${task.updated_at || ''}`
    items.push({
      notification_id: id,
      category: 'human',
      title: '任务等待人工确认',
      content: `${task.display_name || task.name || '当前任务'} 需要在工作台处理人工确认后才能继续运行。`,
      is_read: readIds.has(id),
      created_at: task.updated_at || task.created_at || new Date().toISOString(),
      task_id: taskId,
      target_path: '/workspace',
      severity: 'info',
    })
  }

  items.sort((a, b) => Number(a.is_read) - Number(b.is_read) || new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  return { items }
}

export async function warmupNotifications() {
  return getNotifications()
}

export function warmupNotificationsSoon(delayMs = 0) {
  const now = Date.now()
  if (now - lastNotificationWarmupAt < 30_000) return
  lastNotificationWarmupAt = now
  globalThis.setTimeout(() => {
    warmupNotifications().catch(() => {})
  }, delayMs)
}

export async function getUnreadNotificationCount() {
  const profile = await getProfile()
  const data = { items: quotaNotificationsFromProfile(profile, readNotificationIds()) }
  return { count: (data.items || []).filter((item) => !item.is_read).length }
}

export async function markNotificationRead(notificationId) {
  if (notificationId) {
    const ids = readNotificationIds()
    ids.add(notificationId)
    writeNotificationIds(ids)
  }
  return { ok: true }
}

export async function markAllNotificationsRead(notificationIds = null) {
  const ids = readNotificationIds()
  if (Array.isArray(notificationIds)) {
    notificationIds.filter(Boolean).forEach((notificationId) => ids.add(String(notificationId)))
  } else {
    const data = await getNotifications()
    ;(data.items || []).forEach((item) => ids.add(item.notification_id))
  }
  writeNotificationIds(ids)
  return { ok: true }
}

function readNotificationIds() {
  try {
    const payload = JSON.parse(localStorage.getItem(NOTIFICATION_READ_KEY) || '[]')
    return new Set(Array.isArray(payload) ? payload.map(String) : [])
  } catch {
    return new Set()
  }
}

function notificationCacheKey() {
  const teamId = getActiveTeamHint()?.id || 'default'
  const user = getCachedUser()
  const userId = user?.id || user?.user_id || 'default'
  return `${NOTIFICATION_CACHE_PREFIX}:${teamId}:${userId}`
}

function readNotificationCache(cacheKey) {
  if (typeof localStorage === 'undefined') return null
  try {
    const payload = JSON.parse(localStorage.getItem(cacheKey) || 'null')
    if (!payload || !Array.isArray(payload.items)) return null
    if (Date.now() - Number(payload.cached_at || 0) >= NOTIFICATION_CACHE_TTL_MS) return null
    return { items: applyNotificationReadState(payload.items) }
  } catch {
    return null
  }
}

function writeNotificationCache(cacheKey, items) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(cacheKey, JSON.stringify({
    cached_at: Date.now(),
    items: Array.isArray(items) ? items : [],
  }))
}

function applyNotificationReadState(items) {
  const readIds = readNotificationIds()
  return items
    .map((item) => ({
      ...item,
      is_read: Boolean(item.is_read || readIds.has(item.notification_id)),
    }))
    .sort((a, b) => Number(a.is_read) - Number(b.is_read) || new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
}

function quotaNotificationsFromProfile(profile, readIds = readNotificationIds()) {
  const remaining = Math.max(0, Number(profile.token_quota || 0) - Number(profile.token_used || 0))
  const quotaExhausted = (
    Number(profile.token_quota || 0) > 0
    && (remaining <= 0 || profile.quota_status === 'exhausted')
  )
  if (!quotaExhausted) return []

  const id = `quota-exhausted:${profile.active_team_id}:${profile.user_id}`
  return [{
    notification_id: id,
    category: 'quota',
    title: '调用额度已用完',
    content: `当前账号 Token 额度已用完（已用 ${Number(profile.token_used || 0)} / 额度 ${Number(profile.token_quota || 0)}），请联系管理员增加额度。`,
    is_read: readIds.has(id),
    created_at: new Date().toISOString(),
    target_path: '/profile',
    severity: 'warning',
  }]
}

function writeNotificationIds(ids) {
  const payload = [...ids].slice(-200)
  localStorage.setItem(NOTIFICATION_READ_KEY, JSON.stringify(payload))
}
