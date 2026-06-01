import { getProfile } from '@/api/auth'
import { getTasks } from '@/api/tasks'

const NOTIFICATION_READ_KEY = 'ai4ml-read-system-notifications'
const HUMAN_WAITING_STATUSES = new Set(['waiting_human', 'paused_for_review'])

export async function getNotifications() {
  const [profile, tasks] = await Promise.all([
    getProfile(),
    getTasks(),
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
